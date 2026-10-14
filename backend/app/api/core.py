"""Framework-free API logic. The FastAPI routes in routes.py only call these methods, so everything here is unit tested."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .. import catalog
from ..ai.facts import MissingBusinessName
from ..context import AppContext
from ..schemas import (
    AdResponse, ConfigResponse, CreativeModeInfo, GenerateAdRequest, HealthResponse, JobResponse, ReadyResponse, ScrapeRequest,
    UploadResponse,
)
from ..scraper.render import browser_installed
from ..services.ads import AI_UNAVAILABLE_MESSAGE, WEBSITE_IMAGE_SECONDS, DailyLimitReached, InvalidCreative, ScanNotReady, UnknownJob
from ..services.assets import VideoUploadProblem
from ..video.images import ImageProblem

UPLOAD_KINDS = {"logo", "photo", "video"}

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """An error with an HTTP status, a stable machine code and a message that is safe to show to users."""

    def __init__(self, status: int, message: str, code: str = "error"):
        """Store the three parts."""
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


@dataclass
class UploadedFile:
    """One uploaded file, already read into memory (size-checked by the caller)."""

    filename: str
    content: bytes


class Api:
    """What each endpoint does, without any web framework."""

    def __init__(self, ctx: AppContext):
        """Keep the application context."""
        self.ctx = ctx

    def _limit(self, client_id: str) -> None:
        """Raise 429 when a client sends too many expensive requests."""
        if not self.ctx.limiter.allow(client_id):
            raise ApiError(429, "Too many requests. Please wait a minute and try again.", "rate_limited")

    # ------------------------------------------------------------------ scan

    async def start_scrape(self, body: ScrapeRequest, client_id: str) -> JobResponse:
        """POST /api/scrape: start (or reuse) a website scan."""
        self._limit(client_id)
        return await self.ctx.scrape_jobs.create(body.url, refresh=body.refresh)

    async def get_job(self, job_id: str) -> JobResponse:
        """GET /api/jobs/{job_id}: progress and result of a scan."""
        job = await self.ctx.scrape_jobs.get(job_id)
        if job is None:
            raise ApiError(404, "That website scan was not found. It may have expired; scan the website again.", "job_not_found")
        return job

    # ------------------------------------------------------------------ uploads

    def upload_limit(self, kind: str) -> int:
        """Largest accepted file for an upload kind, in bytes."""
        s = self.ctx.settings
        return s.max_video_upload_bytes if kind == "video" else s.max_upload_bytes

    async def upload(self, files: list[UploadedFile], kind: str, client_id: str) -> UploadResponse:
        """POST /api/uploads: store a logo, photos or videos (all or nothing)."""
        self._limit(client_id)
        settings = self.ctx.settings
        if kind not in UPLOAD_KINDS:
            raise ApiError(400, "kind must be 'logo', 'photo' or 'video'.", "bad_kind")
        if not files:
            raise ApiError(400, "Choose at least one file.", "no_files")
        limit = 1 if kind == "logo" else settings.max_upload_files
        if len(files) > limit:
            noun = {"logo": "logo", "photo": "photos", "video": "videos"}[kind]
            raise ApiError(400, f"You can upload at most {limit} {noun} at a time.", "too_many_files")
        max_bytes = self.upload_limit(kind)
        saved = []
        try:
            for item in files:
                if len(item.content) > max_bytes:
                    raise ApiError(413, f"{item.filename or 'The file'} is larger than {max_bytes // (1024 * 1024)} MB.", "file_too_large")
                saved.append(await self.ctx.assets.save(item.content, item.filename, kind))
        except ImageProblem as exc:
            await self._rollback(saved)
            code = "bad_video" if isinstance(exc, VideoUploadProblem) else "bad_image"
            raise ApiError(400, f"{files[len(saved)].filename or 'The file'}: {exc}", code) from None
        except ApiError:
            await self._rollback(saved)
            raise
        return UploadResponse(assets=saved)

    async def _rollback(self, assets) -> None:
        """Delete assets saved earlier in a failed upload request."""
        for asset in assets:
            await self.ctx.assets.delete(asset.asset_id)

    async def asset_file(self, asset_id: str) -> tuple[Path, str]:
        """GET /api/assets/{asset_id}: path and media type of an uploaded image or video."""
        found = await self.ctx.assets.find(asset_id)
        if not found:
            raise ApiError(404, "File not found.", "asset_not_found")
        info, path = found
        return path, self.ctx.assets.media_type(path)

    # ------------------------------------------------------------------ ads

    async def create_ad(self, body: GenerateAdRequest, client_id: str) -> AdResponse:
        """POST /api/generate-ad: start ONE ad (one prompt, one video)."""
        self._limit(client_id)
        try:
            return await self.ctx.ads.create(body)
        except MissingBusinessName as exc:
            raise ApiError(422, str(exc), "business_name_required") from None
        except UnknownJob as exc:
            raise ApiError(404, str(exc), "job_not_found") from None
        except ScanNotReady as exc:
            raise ApiError(409, str(exc), "scan_not_ready") from None
        except DailyLimitReached as exc:
            raise ApiError(429, str(exc), "daily_limit") from None
        except InvalidCreative as exc:
            raise ApiError(422, str(exc), exc.code) from None

    async def cancel_ad(self, ad_id: str) -> AdResponse:
        """POST /api/ads/{ad_id}/cancel: stop an ad that is still being made."""
        await self.get_ad(ad_id)  # 404 for unknown ids
        if not await self.ctx.ads.cancel(ad_id):
            raise ApiError(409, "This ad is already finished and cannot be cancelled.", "ad_finished")
        return await self.get_ad(ad_id)

    async def get_ad(self, ad_id: str) -> AdResponse:
        """GET /api/ads/{ad_id}: progress, prompt and result of an ad."""
        ad = await self.ctx.ads.get(ad_id)
        if ad is None:
            raise ApiError(404, "That ad was not found. It may have expired.", "ad_not_found")
        return ad

    async def ad_video(self, ad_id: str) -> Path:
        """GET /api/ads/{ad_id}/video: path of the finished MP4."""
        ad = await self.get_ad(ad_id)
        path = self.ctx.ads.video_path(ad_id)
        if path is None:
            if ad.status == "failed":
                raise ApiError(404, "This ad has no video because it failed.", "no_video")
            raise ApiError(409, "The video is not ready yet.", "video_not_ready")
        return path

    # ------------------------------------------------------------------ meta

    def config(self) -> ConfigResponse:
        """GET /api/config: what this server can do, so the frontend never hard-codes options."""
        s = self.ctx.settings
        durations = [d for d in catalog.DURATION_CHOICES if d <= s.video_max_seconds] or [max(1, s.video_max_seconds)]
        listed = lambda table, *keys: [{"id": key, **{k: v[k] for k in keys}} for key, v in table.items()]  # noqa: E731
        ai_ok = self.ctx.ads.ai_video_available
        writer = self.ctx.prompts.mode == "llm"
        ai_reason = "" if ai_ok else AI_UNAVAILABLE_MESSAGE
        modes = [
            CreativeModeInfo(
                id="manual", creation_mode="manual", label="Manual ad",
                description="Upload your own images or videos and add a QR code, text and logo. Built with FFmpeg only: no website scan and no AI video.",
                uses_scraper=False, uses_prompt_writer=False, uses_ai_video=False,
            ),
            CreativeModeInfo(
                id="website", creation_mode="auto", label="Website Content Priority",
                description="Uses the original images and details from your website: each image plays for 3 seconds (looping if there are few), with motion, text, logo and QR code added by FFmpeg. No AI video is generated.",
                uses_scraper=True, uses_prompt_writer=False, uses_ai_video=False,
            ),
            CreativeModeInfo(
                id="ai", creation_mode="auto", label="AI Video Priority",
                description="Only AI-generated footage: your scraped business details become ONE checked prompt and the AI model creates the video (no website pictures). Short clips loop to your chosen length; QR code and verified details are added afterwards.",
                uses_scraper=True, uses_prompt_writer=writer, uses_ai_video=True, available=ai_ok, unavailable_reason=ai_reason,
            ),
            CreativeModeInfo(
                id="mixed", creation_mode="auto", label="Website + AI Mix",
                description="Opens and closes with your original website images and puts an AI-generated video in the middle, joined with FFmpeg.",
                uses_scraper=True, uses_prompt_writer=writer, uses_ai_video=True, available=ai_ok, unavailable_reason=ai_reason,
            ),
        ]
        return ConfigResponse(
            demo_mode=s.effective_video_provider == "mock",
            video_provider=s.effective_video_provider,
            prompt_builder=self.ctx.prompts.mode,  # type: ignore[arg-type]
            max_video_seconds=s.video_max_seconds,
            durations=durations,
            platforms=listed(catalog.PLATFORMS, "label", "aspect_ratio", "audience"),
            goals=listed(catalog.GOALS, "label"),
            styles=listed(catalog.STYLES, "label"),
            tones=listed(catalog.TONES, "label"),
            categories=[{"id": key, "label": label} for key, label in catalog.CATEGORIES.items()],
            max_upload_bytes=s.max_upload_bytes,
            max_upload_files=s.max_upload_files,
            phase2_mode=s.phase2_mode,
            ai_video_available=ai_ok,
            ai_video_message=f"AI video provider: {s.effective_video_provider}." if ai_ok else ai_reason,
            creative_modes=modes,
            compose_durations=list(catalog.DURATION_CHOICES),
            website_image_seconds=WEBSITE_IMAGE_SECONDS,
            max_video_upload_bytes=s.max_video_upload_bytes,
            max_video_upload_seconds=s.max_video_upload_seconds,
        )

    @staticmethod
    def health() -> HealthResponse:
        """GET /health: the process is alive."""
        return HealthResponse()

    async def ready(self) -> ReadyResponse:
        """GET /ready: dependencies are usable (database, cache, browser). Problems are listed, never secrets."""
        s = self.ctx.settings
        problems: list[str] = []
        database = await self.ctx.db.ping()
        if not database:
            problems.append("The database does not answer.")
        redis = None
        if s.redis_url:
            redis = await self.ctx.cache.ping()
            if not redis:
                problems.append("Redis is configured but does not answer; results are cached in memory instead.")
        ok, detail = await browser_installed(s.playwright_browser)
        if not ok:
            problems.append(f"Websites that need JavaScript cannot be read: {detail}")
        if self.ctx.video.provider_name == "mock":
            problems.append("Demo mode: no VIDEO_MODEL_API_KEY is set, so videos are simple zoom clips.")
        return ReadyResponse(
            status="ok" if database else "degraded", database=database, redis=redis, video_provider=self.ctx.video.provider_name,
            prompt_builder=self.ctx.prompts.mode, browser=f"{s.playwright_browser}: {detail}", problems=problems,
        )
