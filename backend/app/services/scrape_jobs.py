"""Scrape jobs: run the two-phase scraper in the background, track progress, cache results per site."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Optional

from ..config import Settings
from ..schemas import SCHEMA_VERSION, JobResponse, Phase2Info, ScrapeResult, utcnow
from ..scraper.fetch import Deadline
from ..scraper.safety import UnsafeUrlError, normalize_input_url
from ..scraper.service import Scraper
from ..store.cache import Cache
from ..store.db import Database

logger = logging.getLogger(__name__)

STAGE_PROGRESS = {"queued": 0, "fetching": 15, "rendering": 45, "extracting": 70, "ad_ready": 85}
STAGE_MESSAGES = {
    "fetching": "Opening your website…",
    "rendering": "This site loads with JavaScript, reading it with a browser…",
    "extracting": "Finding your business details…",
    "ad_ready": "Ready to draft your ad.",
}


class ScrapeJobs:
    """Creates scrape jobs, runs them in the background and answers polling requests."""

    def __init__(self, settings: Settings, db: Database, cache: Cache, scraper: Scraper):
        """Wire the collaborators; nothing runs until create() is called."""
        self.settings = settings
        self.db = db
        self.cache = cache
        self.scraper = scraper
        self._active: dict[str, JobResponse] = {}
        self._by_key: dict[str, str] = {}
        self._tasks: set[asyncio.Task] = set()
        self._sem = asyncio.Semaphore(max(1, settings.max_concurrent_scrapes))

    # ------------------------------------------------------------------ public API

    async def recover(self) -> int:
        """After a restart, close jobs that were still running (their task died with the old process)."""
        stuck = await self.db.list_by_status("job", ["queued", "running"])
        for data in stuck:
            job = JobResponse.model_validate(data)
            job.status, job.is_final, job.progress = "internal_error", True, 100
            job.message = "The server restarted while scanning. Please scan the website again."
            job.phase2.state = "failed" if job.phase2.state == "running" else job.phase2.state
            await self._save(job)
        return len(stuck)

    async def create(self, raw_url: str, refresh: bool = False) -> JobResponse:
        """Start (or reuse) a scrape job for a URL and return its first snapshot."""
        try:
            normalized = normalize_input_url(raw_url, self.scraper.policy)
            key, shown_url = normalized.cache_key, normalized.url
        except UnsafeUrlError:
            key, shown_url = "", raw_url  # the scraper reports invalid_url / unsupported_platform with a friendly message

        if key and not refresh:
            cached = await self._cached(key)
            if cached is not None:
                return await self._cached_job(shown_url, cached)
        if key and key in self._by_key and self._by_key[key] in self._active:  # same site already being scanned
            return self._active[self._by_key[key]].model_copy(deep=True)

        job = JobResponse(job_id=uuid.uuid4().hex, url=shown_url, status="queued", stage="queued", progress=0, message="Waiting to start…")
        self._active[job.job_id] = job
        if key:
            self._by_key[key] = job.job_id
        await self._save(job)
        task = asyncio.create_task(self._run(job.job_id, raw_url, key), name=f"scrape-{job.job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job.model_copy(deep=True)

    async def get(self, job_id: str) -> Optional[JobResponse]:
        """Current snapshot of a job (memory while running, database afterwards), or None."""
        live = self._active.get(job_id)
        if live is not None:
            return live.model_copy(deep=True)
        data = await self.db.get("job", job_id)
        return JobResponse.model_validate(data) if data else None

    async def close(self) -> None:
        """Cancel running jobs on shutdown and wait for them to stop."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ cache

    def _cache_key(self, key: str) -> str:
        """Cache key including the schema version so old shapes never leak in."""
        return f"scrape:v{SCHEMA_VERSION}:{key}"

    async def _cached(self, key: str) -> Optional[ScrapeResult]:
        """Cached result for a site, or None (a broken cache entry counts as a miss)."""
        raw = await self.cache.get(self._cache_key(key))
        if not raw:
            return None
        try:
            return ScrapeResult.model_validate_json(raw)
        except ValueError:
            await self.cache.delete(self._cache_key(key))
            return None

    async def _cached_job(self, url: str, result: ScrapeResult) -> JobResponse:
        """A finished job built from a cached result (stored so GET /jobs/{id} keeps working)."""
        done = result.status in {"ok", "partial"}
        job = JobResponse(
            job_id=uuid.uuid4().hex, url=url, status=result.status, stage="ad_ready" if done else "fetching", progress=100,
            message=result.message, cached=True, is_final=True,
            phase2=Phase2Info(state="done" if result.meta.phase >= 2 else "skipped", pages_done=len(result.pages), pages_total=len(result.pages)),
            result=result,
        )
        await self._save(job)
        return job

    async def _store_in_cache(self, key: str, result: ScrapeResult) -> None:
        """Cache good results for SCRAPE_CACHE_TTL_HOURS, partial/blocked ones briefly, everything else not at all."""
        if not key:
            return
        short = max(60.0, self.settings.blocked_cache_ttl_minutes * 60.0)
        if result.status == "ok":
            ttl = self.settings.scrape_cache_ttl_hours * 3600.0
        elif result.status in {"partial", "blocked"}:
            ttl = min(short, self.settings.scrape_cache_ttl_hours * 3600.0)
        else:
            return
        await self.cache.set(self._cache_key(key), result.model_dump_json(), ttl)

    # ------------------------------------------------------------------ running a job

    async def _save(self, job: JobResponse) -> None:
        """Persist a job snapshot."""
        job.updated_at = utcnow()
        try:
            await self.db.put("job", job.job_id, job.model_dump(mode="json"), status=job.status)
        except Exception:  # a failing disk write must not kill the scrape
            logger.exception("could not save job %s", job.job_id)

    async def _update(self, job: JobResponse, **changes) -> None:
        """Apply field changes to a live job and persist it."""
        for name, value in changes.items():
            setattr(job, name, value)
        await self._save(job)

    async def _finish(self, job: JobResponse, result: ScrapeResult, key: str, phase2_state: str) -> None:
        """Mark a job final with its result and cache it."""
        job.result = result
        job.phase2.state = phase2_state  # type: ignore[assignment]
        await self._update(
            job, status=result.status, progress=100, message=result.message, is_final=True,
            stage="ad_ready" if result.status in {"ok", "partial"} else job.stage,
        )
        await self._store_in_cache(key, result)

    async def _run(self, job_id: str, raw_url: str, key: str) -> None:
        """Task body: phase 1, then phase 2, then cache; always ends with a final job."""
        job = self._active[job_id]
        started = time.monotonic()
        try:
            async with self._sem:
                await self._update(job, status="running", stage="fetching", progress=STAGE_PROGRESS["fetching"], message=STAGE_MESSAGES["fetching"])
                overall = Deadline(self.settings.max_scrape_seconds)

                async def on_stage(stage: str, message: str, partial: Optional[ScrapeResult]) -> None:
                    """Phase 1 progress: move the stage forward, never backwards."""
                    if stage not in STAGE_PROGRESS or STAGE_PROGRESS[stage] < job.progress:
                        return
                    changes: dict = {"stage": stage, "progress": STAGE_PROGRESS[stage], "message": message or STAGE_MESSAGES.get(stage, "")}
                    if stage == "ad_ready" and partial is not None:
                        changes["result"] = partial
                    await self._update(job, **changes)

                outcome = await self.scraper.scrape_phase1(raw_url, overall.child(self.settings.max_phase1_seconds), on_stage)
                if outcome.session is None:
                    await self._finish(job, outcome.result, key, "skipped")
                    return
                if not self.scraper.should_run_phase2(outcome.result):
                    await self._finish(job, outcome.result, key, "skipped")
                    return

                job.result = outcome.result
                job.phase2 = Phase2Info(state="running")
                await self._update(job, stage="ad_ready", progress=STAGE_PROGRESS["ad_ready"], message="Draft ready. Reading more pages in the background…")

                async def on_pages(done: int, total: int, partial: ScrapeResult) -> None:
                    """Phase 2 progress: pages read so far."""
                    job.phase2.pages_done, job.phase2.pages_total = done, total
                    job.progress = min(99, STAGE_PROGRESS["ad_ready"] + (14 * done // total if total else 0))
                    await self._save(job)

                final = await self.scraper.scrape_phase2(outcome.session, overall, on_pages)
                await self._finish(job, final, key, "done")
        except asyncio.CancelledError:
            job.status, job.is_final, job.progress = "internal_error", True, 100
            job.message = "The server is shutting down. Please scan again."
            await self._save(job)
            raise
        except Exception:
            logger.exception("scrape job %s crashed", job_id)
            result = ScrapeResult(status="internal_error", message="Something went wrong while reading the website. Please try again, or enter your business details instead.")
            await self._finish(job, result, "", "failed" if job.phase2.state == "running" else "skipped")
        finally:
            self._active.pop(job_id, None)
            if self._by_key.get(key) == job_id:
                self._by_key.pop(key, None)
            logger.info("scrape job %s finished in %.1fs with status %s", job_id, time.monotonic() - started, job.status)
            await self.release_browser()

    async def release_browser(self) -> None:
        """Close Firefox once no scan is running, so a later video job has the memory."""
        if self._active:
            return
        try:
            await self.scraper.pool.close()
        except Exception:
            logger.warning("the browser did not close", exc_info=True)
