"""The ad pipeline. One request = one ad, run in the background. Which steps run depends on the creative mode:

  manual   uploaded images/videos -> FFmpeg compose -> overlays           (no scan, no prompt writer, no AI video)
  website  original website images, 3 s each, looped to the length -> FFmpeg -> overlays   (no prompt writer, no AI video)
  ai       facts -> ONE prompt -> AI text-to-video (no website images) -> looped to the length -> overlays
  mixed    website image(s) -> AI video (looped to the length) -> website image(s) -> overlays
  legacy   (request without `creative`) facts -> hero -> ONE prompt -> video -> overlays, exactly as before

The backend decides what runs from the validated CreativeConfig; the AI provider is only called when the mode allows it.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..ai.facts import FactSheet, build_fact_sheet
from ..ai.scene import about_line, visual_items
from ..ai.prompt_builder import PromptBuilder
from ..config import Settings
from ..schemas import (
    AdBrief, AdPrompt, AdResponse, AssetInfo, CompositionSegment, CreativeConfig, GenerateAdRequest, ReferenceImage, ScrapeResult, utcnow,
)
from ..scraper.fetch import Deadline
from ..scraper.service import Scraper
from ..store.db import Database
from ..video.base import VideoError, VideoRequest, output_size, probe_media
from ..video.compose import Segment, compose
from ..video.finalize import OverlaySpec, finalize_video
from ..video.images import ImageProblem, PreparedImage, download_image, prepare_frame, prepare_hero, prepare_logo
from ..video.quality import check_output
from ..video.service import VideoService
from .assets import AssetStore
from .scrape_jobs import ScrapeJobs

logger = logging.getLogger(__name__)

AD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
PROMPT_WAIT_SECONDS = 90.0
HERO_ATTEMPTS = 6
GENERIC_ERROR = "Something went wrong while creating the ad. Please try again."
WEBSITE_IMAGE_SECONDS = 2.5  # opening / closing website images around an AI clip
WEBSITE_SLOT_SECONDS = 3.0  # website-content ads show each image for 3 seconds
MIN_IMAGE_SECONDS = 1.5  # shortest time one image is shown
UPLOAD_IMAGE_SECONDS_WITH_VIDEO = 3.0  # uploaded photos shown next to an uploaded video
MAX_WEBSITE_IMAGES = {"website": 8, "mixed": 4}
CANCELLED_MESSAGE = "You cancelled this ad."


class UnknownJob(LookupError):
    """The scan job id does not exist (or expired)."""


class ScanNotReady(RuntimeError):
    """The scan has not produced a first result yet."""


class DailyLimitReached(RuntimeError):
    """MAX_ADS_PER_DAY was reached."""


class InvalidCreative(ValueError):
    """The creative configuration cannot be used with this server or these inputs. The message is safe to show."""

    def __init__(self, message: str, code: str = "invalid_creative"):
        """Keep a machine code next to the message."""
        super().__init__(message)
        self.code = code


class AiVideoUnavailable(InvalidCreative):
    """An AI video mode was requested but no AI video provider is configured."""

    def __init__(self, message: str):
        """Fixed machine code."""
        super().__init__(message, "ai_video_unavailable")


AI_UNAVAILABLE_MESSAGE = (
    "AI video generation is not available on this server: no AI video provider is configured (VIDEO_MODEL_API_KEY is empty). "
    "Choose Website Content or a manual ad, or ask the administrator to add a video provider key."
)


def website_slots(duration: float) -> list[float]:
    """3-second image slots that add up to the ad length (5 s -> 3+2, 15 s -> 5 x 3, 20 s -> 6 x 3 + 2).

    A remainder under 1.5 s is added to the last slot instead of becoming a flash.
    """
    full, rest = divmod(float(duration), WEBSITE_SLOT_SECONDS)
    slots = [WEBSITE_SLOT_SECONDS] * int(full)
    if not slots:
        return [float(duration)]
    if rest >= MIN_IMAGE_SECONDS:
        slots.append(round(rest, 3))
    elif rest > 0:
        slots[-1] += rest
    return slots


@dataclass
class HeroSelection:
    """The ONE image used as the first frame (or none), plus what happened while choosing it."""

    prepared: Optional[PreparedImage] = None
    reference: Optional[ReferenceImage] = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class AdPlan:
    """Everything decided (and validated) before the background run starts."""

    request: GenerateAdRequest
    creative: Optional[CreativeConfig]  # None = the original flow
    scrape: Optional[ScrapeResult]
    facts: Optional[FactSheet]  # None for manual ads: their text comes straight from what the user typed
    duration: int  # AI clip length (ai / mixed / legacy) or target length (website / manual)
    target_seconds: int = 0  # ai / mixed: the length the AI part is looped to
    media: list[tuple[AssetInfo, Path]] = field(default_factory=list)
    website_images: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def mode(self) -> str:
        """legacy | manual | website | ai | mixed."""
        if self.creative is None:
            return "legacy"
        if self.creative.creation_mode == "manual":
            return "manual"
        return self.creative.creative_mode or "ai"

    @property
    def uses_ai_video(self) -> bool:
        """True when the video provider is part of this ad."""
        return self.mode in {"legacy", "ai", "mixed"}


@dataclass
class Made:
    """The video before overlays, and what it is made of."""

    path: Path
    segments: list[CompositionSegment]
    fallback_used: bool = False
    ai_video_used: bool = False
    provider: str = "ffmpeg"


CAPTION_MAX_CHARS = 70
DANGLING_WORDS = {"in", "on", "at", "of", "for", "to", "and", "or", "the", "a", "an", "with", "from", "by", "across", "your", "our", "every", "each", "that", "which", "who", "more", "very"}


def _short(text: str) -> str:
    """One readable caption: the first sentence, cut at a clause or word boundary when it is long."""
    sentence = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))[0].rstrip(".")
    if len(sentence) <= CAPTION_MAX_CHARS:
        return sentence
    clause = re.split(r"\s*[–—]\s*|[,;:]\s|\s-\s", sentence)[0]  # em/en dashes split even without spaces
    if 12 <= len(clause) <= CAPTION_MAX_CHARS:
        return clause
    # cut before a trailing phrase ("... in Mumbai, Delhi"), never leaving a dangling "in", "and", "the" at the end
    words = sentence[:CAPTION_MAX_CHARS].rsplit(" ", 1)[0].split()
    for joiner in (" in ", " across ", " for ", " with ", " at ", " from "):
        head = " ".join(words).rsplit(joiner, 1)[0]
        if head != " ".join(words) and len(head) >= 20:
            words = head.split()
            break
    while len(words) > 3 and words[-1].lower() in DANGLING_WORDS:
        words.pop()
    return " ".join(words).rstrip(",;:")


def key_messages(facts: FactSheet, brief: Optional[AdBrief] = None) -> list[str]:
    """Up to three short on-screen messages that say what the ad is about (main message, then real services)."""
    messages: list[str] = []
    main = (brief.main_message if brief else "") or about_line(facts)
    if main:
        messages.append(_short(main))
    for item in visual_items(facts)[:2]:
        caption = item[:1].upper() + item[1:]
        if caption.lower() not in {m.lower() for m in messages}:
            messages.append(caption)
    return [m for m in messages if m][:3]


def _skippable(url: str) -> bool:
    """Vector or animated images cannot become video frames."""
    return url.lower().split("?")[0].endswith((".svg", ".gif"))


def _segments(result) -> list[CompositionSegment]:
    """Public description of what a composition contains."""
    return [CompositionSegment(kind=s.kind, source=s.source, seconds=s.seconds) for s in result.segments]  # type: ignore[arg-type]


def scan_warnings(scrape: Optional[ScrapeResult]) -> list[str]:
    """Plain-language notes about an incomplete scan (for example a JavaScript site read without a browser)."""
    if scrape is None:
        return []
    flags = set(scrape.flags)
    if "browser_unavailable" in flags:
        return [
            "This website builds its pages with JavaScript, but the browser renderer (Playwright) is not available on the server, "
            "so only the plain HTML was read. Some images or details may be missing."
        ]
    if "render_failed" in flags or "empty_after_render" in flags:
        return ["This website needs JavaScript and could not be fully rendered, so some images or details may be missing."]
    return []


class Ads:
    """Creates ads and runs the pipeline for the chosen mode."""

    def __init__(
        self, settings: Settings, db: Database, scrape_jobs: ScrapeJobs, scraper: Scraper, assets: AssetStore,
        prompts: PromptBuilder, video: VideoService,
    ):
        """Wire the collaborators."""
        self.settings = settings
        self.db = db
        self.scrape_jobs = scrape_jobs
        self.scraper = scraper
        self.assets = assets
        self.prompts = prompts
        self.video = video
        self.videos_dir = settings.data_dir / "videos"
        self.work_dir = settings.data_dir / "work"
        self._active: dict[str, AdResponse] = {}
        self._prompt_ready: dict[str, asyncio.Event] = {}
        self._tasks: set[asyncio.Task] = set()
        self._task_by_ad: dict[str, asyncio.Task] = {}
        self._cancel_requested: set[str] = set()
        self._video_slots = asyncio.Semaphore(max(1, settings.max_concurrent_ads))

    @property
    def ai_video_available(self) -> bool:
        """True when a real AI video provider (not the offline demo) is configured."""
        return self.video.provider_name != "mock"

    # ------------------------------------------------------------------ public API

    async def recover(self) -> int:
        """After a restart, fail ads whose task died with the old process."""
        stuck = await self.db.list_by_status("ad", ["queued", "running"])
        for data in stuck:
            ad = AdResponse.model_validate(data)
            ad.status, ad.stage, ad.progress = "failed", "failed", 100
            ad.error = "The server restarted while creating this ad. Please create it again."
            ad.message = "The ad could not be finished."
            await self._save(ad)
        return len(stuck)

    async def create(self, request: GenerateAdRequest) -> AdResponse:
        """Validate, start the pipeline in the background and (for AI modes, optionally) wait until the prompt is ready."""
        if self.settings.max_ads_per_day > 0:
            if await self.db.count_since("ad", time.time() - 86400) >= self.settings.max_ads_per_day:
                raise DailyLimitReached(f"The daily limit of {self.settings.max_ads_per_day} ads was reached. Try again tomorrow.")
        plan = await self._plan(request)

        ad = AdResponse(
            ad_id=uuid.uuid4().hex, job_id=request.job_id, status="queued", stage="queued", progress=2,
            message="Starting…", warnings=list(plan.warnings), options=request.options, creative=request.creative,
            provider=self.video.provider_name if plan.uses_ai_video else "ffmpeg",
            actual_duration_seconds=plan.duration if plan.mode == "legacy" else None,
        )
        self._active[ad.ad_id] = ad
        prompt_ready = asyncio.Event()
        self._prompt_ready[ad.ad_id] = prompt_ready
        await self._save(ad)
        task = asyncio.create_task(self._run(ad.ad_id, plan), name=f"ad-{ad.ad_id}")
        self._tasks.add(task)
        self._task_by_ad[ad.ad_id] = task
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda _t, ad_id=ad.ad_id: self._task_by_ad.pop(ad_id, None))
        if request.wait_for_prompt and plan.uses_ai_video:
            try:
                await asyncio.wait_for(prompt_ready.wait(), PROMPT_WAIT_SECONDS)
            except asyncio.TimeoutError:
                pass
        return await self.get(ad.ad_id) or ad

    async def get(self, ad_id: str) -> Optional[AdResponse]:
        """Current snapshot of an ad, or None."""
        live = self._active.get(ad_id)
        if live is not None:
            return live.model_copy(deep=True)
        if not AD_ID_RE.match(ad_id or ""):
            return None
        data = await self.db.get("ad", ad_id)
        return AdResponse.model_validate(data) if data else None

    async def cancel(self, ad_id: str) -> bool:
        """Stop a running ad. Returns False when it is not running (unknown or already finished)."""
        task = self._task_by_ad.get(ad_id)
        if task is None or task.done():
            return False
        self._cancel_requested.add(ad_id)
        task.cancel()
        await asyncio.wait({task}, timeout=15)
        return True

    def video_path(self, ad_id: str) -> Optional[Path]:
        """Path of a finished video file (validated id, so no path tricks), or None."""
        if not AD_ID_RE.match(ad_id or ""):
            return None
        path = self.videos_dir / f"{ad_id}.mp4"
        return path if path.is_file() else None

    async def purge_older_than(self, cutoff_ts: float) -> int:
        """Delete old ads and their files (retention). Returns how many were removed."""
        records = await self.db.pop_older_than("ad", cutoff_ts)
        for record in records:
            ad_id = record.get("ad_id", "")
            if AD_ID_RE.match(ad_id):
                (self.videos_dir / f"{ad_id}.mp4").unlink(missing_ok=True)
                shutil.rmtree(self.work_dir / ad_id, ignore_errors=True)
        return len(records)

    async def close(self) -> None:
        """Cancel running pipelines on shutdown."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ planning (runs inside the HTTP request: fast checks only)

    async def _plan(self, request: GenerateAdRequest) -> AdPlan:
        """Resolve the scan, facts, uploads and images, and refuse combinations this server cannot honour."""
        creative = request.creative
        if creative is None:
            scrape = await self._resolve_scrape(request)
            facts = build_fact_sheet(scrape, request.business, request.options)  # raises MissingBusinessName
            duration = min(request.options.duration_seconds, max(1, self.settings.video_max_seconds))
            warnings = [] if duration >= request.options.duration_seconds else [
                f"The video model makes up to {duration} seconds, so this ad is {duration} seconds long."
            ]
            return AdPlan(request, None, scrape, facts, duration, warnings=warnings)

        if creative.calls_ai_video and not self.ai_video_available:
            raise AiVideoUnavailable(AI_UNAVAILABLE_MESSAGE)
        media = await self._resolve_media(creative)
        if creative.creation_mode == "manual":
            return AdPlan(request, creative, None, None, request.options.duration_seconds, media=media)

        scrape = await self._resolve_scrape(request)
        facts = build_fact_sheet(scrape, request.business, request.options)  # raises MissingBusinessName
        warnings = scan_warnings(scrape)
        mode = creative.creative_mode or "ai"
        website_images: list[str] = []
        if creative.use_website_images:
            website_images = self._website_images(creative, scrape, mode, request.options.duration_seconds)
            has_uploaded_images = any(info.media_type == "image" for info, _ in media)
            if not website_images and (mode == "mixed" or not has_uploaded_images):
                raise InvalidCreative(
                    "The website scan found no usable images. Upload photos, pick other images, or choose AI Video Priority.", "no_images",
                )
        requested = request.options.duration_seconds
        if mode == "website":
            return AdPlan(request, creative, scrape, facts, requested, media=media, website_images=website_images, warnings=warnings)
        clip = min(requested, max(1, self.settings.video_max_seconds))
        if clip < requested:
            warnings.append(f"The AI video model makes clips of up to {clip} seconds, so the AI clip is looped to fill {requested} seconds.")
        return AdPlan(
            request, creative, scrape, facts, clip, target_seconds=requested, media=media, website_images=website_images, warnings=warnings,
        )

    @staticmethod
    def _website_images(creative: CreativeConfig, scrape: Optional[ScrapeResult], mode: str, duration: int) -> list[str]:
        """The website images to use: the user's choice (only images the scan found) or the scan's best ones."""
        found = list(scrape.images) if scrape else []
        limit = MAX_WEBSITE_IMAGES.get(mode, 2)
        if creative.selected_image_urls:
            unknown = [url for url in creative.selected_image_urls if url not in found]
            if unknown:
                raise InvalidCreative("Only images found by the website scan can be selected. Scan the website again and pick from its images.", "unknown_image")
            chosen = [url for url in creative.selected_image_urls if not _skippable(url)]
        else:
            default_count = len(website_slots(duration)) if mode == "website" else 2
            chosen = [url for url in found if not _skippable(url)][:default_count]
        return chosen[:limit]

    async def _resolve_media(self, creative: CreativeConfig) -> list[tuple[AssetInfo, Path]]:
        """Look up every uploaded file the configuration names; refuse missing ones and the wrong kind."""
        media: list[tuple[AssetInfo, Path]] = []
        for asset_id in creative.media_asset_ids:
            found = await self.assets.find(asset_id)
            if not found:
                raise InvalidCreative("An uploaded file was not found. It may have expired; upload it again.", "asset_not_found")
            info, path = found
            if info.kind == "logo":
                raise InvalidCreative("A logo cannot be used as ad media. Upload it as the logo instead.", "bad_media")
            if creative.creation_mode == "auto" and info.media_type == "video":
                raise InvalidCreative("Auto ads use uploaded photos only. Create a manual ad to build it from your own video.", "bad_media")
            media.append((info, path))
        return media

    # ------------------------------------------------------------------ helpers

    async def _save(self, ad: AdResponse) -> None:
        """Persist an ad snapshot."""
        ad.updated_at = utcnow()
        try:
            await self.db.put("ad", ad.ad_id, ad.model_dump(mode="json"), status=ad.status)
        except Exception:
            logger.exception("could not save ad %s", ad.ad_id)

    async def _set(self, ad: AdResponse, **changes) -> None:
        """Apply changes to a live ad and persist (stage changes are logged)."""
        if "stage" in changes and changes["stage"] != ad.stage:
            logger.info("ad %s stage %s -> %s: %s", ad.ad_id, ad.stage, changes["stage"], changes.get("message", ad.message))
        for name, value in changes.items():
            setattr(ad, name, value)
        await self._save(ad)

    @staticmethod
    def _warn(ad: AdResponse, *messages: str) -> None:
        """Add warnings once each."""
        for message in messages:
            if message and message not in ad.warnings:
                ad.warnings.append(message)

    async def _resolve_scrape(self, request: GenerateAdRequest) -> Optional[ScrapeResult]:
        """The scrape result to use: the stored job's, the one in the request, or none (manual details only)."""
        if request.job_id:
            job = await self.scrape_jobs.get(request.job_id)
            if job is None:
                raise UnknownJob("That website scan was not found. Scan the website again.")
            if job.result is None:
                raise ScanNotReady("The website scan is not ready yet. Wait a moment and try again.")
            return job.result
        return request.scrape_result

    # ------------------------------------------------------------------ images

    async def _read_asset(self, asset_id: str) -> Optional[bytes]:
        """Bytes of an uploaded asset, or None when it does not exist."""
        found = await self.assets.find(asset_id)
        if not found:
            return None
        return await asyncio.to_thread(found[1].read_bytes)

    def _hero_candidates(self, plan: AdPlan) -> list[tuple[str, str]]:
        """Candidate first-frame images in order of preference: (source, url or asset id)."""
        request, scrape, creative = plan.request, plan.scrape, plan.creative
        candidates: list[tuple[str, str]] = []
        if request.hero:
            candidates.append((request.hero.source, (request.hero.asset_id if request.hero.source == "asset" else request.hero.url) or ""))
        if creative is None:
            candidates += [("asset", asset_id) for asset_id in request.photo_asset_ids[:3]]
            candidates += [("scraped", url) for url in (scrape.images if scrape else [])]
            return candidates
        website = [("scraped", url) for url in plan.website_images + (scrape.images if scrape else [])]
        uploads = [("asset", info.asset_id) for info, _ in plan.media if info.media_type == "image"]
        return candidates + (website + uploads if creative.prefer_website_images else uploads + website)

    async def _select_hero(self, plan: AdPlan, aspect: str, folder: Path) -> HeroSelection:
        """Pick the ONE reference image for the video model: the user's choice first, then the best image that works."""
        selection = HeroSelection()
        chosen = plan.request.hero
        seen: set[tuple[str, str]] = set()
        ordered = [c for c in self._hero_candidates(plan) if c[1] and not (c in seen or seen.add(c))][:HERO_ATTEMPTS + 3]

        deadline = Deadline(45.0)
        best: Optional[tuple[PreparedImage, tuple[str, str]]] = None
        attempts = 0
        for index, (source, ref) in enumerate(ordered):
            if deadline.expired or attempts >= HERO_ATTEMPTS:
                break
            if source == "scraped" and _skippable(ref):
                continue
            attempts += 1
            target = folder / f"hero-{index}.jpg"
            try:
                raw = await self._read_asset(ref) if source == "asset" else await download_image(
                    self.scraper.fetcher, ref, max_bytes=self.settings.max_upload_bytes, seconds=min(15.0, deadline.remaining())
                )
                if raw is None:
                    raise ImageProblem("That uploaded image no longer exists.")
                prepared = await asyncio.to_thread(prepare_hero, raw, target, aspect, min_side=self.settings.hero_min_side_px)
            except ImageProblem as exc:
                logger.info("hero candidate %s rejected: %s", ref[:80], exc)
                if chosen and index == 0:
                    selection.warnings.append(f"Your chosen hero image could not be used ({exc}). Another image was used instead.")
                continue
            if not prepared.warnings:
                best = (prepared, (source, ref))
                break
            if best is None or min(prepared.width, prepared.height) > min(best[0].width, best[0].height):
                best = (prepared, (source, ref))  # usable but small: keep looking, remember the best one
        if best is None:
            selection.warnings.append("No usable image was found, so the video starts from a plain background. Upload a photo for a better ad.")
            return selection
        prepared, (source, ref) = best
        selection.prepared = prepared
        selection.warnings.extend(prepared.warnings)
        selection.reference = ReferenceImage(
            source=source, url=ref if source == "scraped" else None, asset_id=ref if source == "asset" else None,  # type: ignore[arg-type]
            width=prepared.width, height=prepared.height,
        )
        return selection

    async def _website_frames(
        self, ad: AdResponse, urls: list[str], folder: Path, aspect: str, size: tuple[int, int],
    ) -> list[tuple[str, Path]]:
        """Download (through the SSRF-safe fetcher) and fit the chosen website images. Images that fail are skipped with a warning."""
        frames: list[tuple[str, Path]] = []
        deadline = Deadline(60.0)
        for index, url in enumerate(urls):
            if deadline.expired:
                self._warn(ad, "Some website images were skipped because downloading them took too long.")
                break
            try:
                raw = await download_image(self.scraper.fetcher, url, max_bytes=self.settings.max_upload_bytes, seconds=min(15.0, deadline.remaining()))
                prepared = await asyncio.to_thread(
                    prepare_frame, raw, folder / f"web-{index}.jpg", aspect, size=size, min_side=self.settings.hero_min_side_px,
                )
            except ImageProblem as exc:
                logger.info("website image %s skipped: %s", url[:80], exc)
                self._warn(ad, f"A website image was skipped ({exc}).")
                continue
            self._warn(ad, *prepared.warnings)
            frames.append((url, prepared.path))
        return frames

    async def _upload_frames(self, ad: AdResponse, plan: AdPlan, folder: Path, aspect: str, size: tuple[int, int]) -> list[tuple[str, Path]]:
        """Fit the uploaded photos of this ad into video frames."""
        frames: list[tuple[str, Path]] = []
        for index, (info, path) in enumerate(plan.media):
            if info.media_type != "image":
                continue
            raw = await asyncio.to_thread(path.read_bytes)
            prepared = await asyncio.to_thread(
                prepare_frame, raw, folder / f"upload-{index}.jpg", aspect, size=size, min_side=self.settings.hero_min_side_px,
            )
            self._warn(ad, *prepared.warnings)
            frames.append((info.asset_id, prepared.path))
        return frames

    async def _prepare_logo(self, plan: AdPlan, folder: Path, ad: AdResponse) -> Optional[Path]:
        """Logo for the overlay: the uploaded one, else (auto ads only) the scraped one (never a page photo or SVG). Failures only warn."""
        request, scrape = plan.request, plan.scrape
        target = folder / "logo.png"
        try:
            if request.logo_asset_id:
                raw = await self._read_asset(request.logo_asset_id)
                if raw is None:
                    ad.warnings.append("Your uploaded logo was not found, so it was left out.")
                    return None
            elif plan.mode != "manual" and scrape and scrape.site.logo and not {"logo_is_og_image", "logo_is_svg"} & set(scrape.flags):
                raw = await download_image(self.scraper.fetcher, scrape.site.logo, max_bytes=2 * 1024 * 1024, seconds=10.0)
            else:
                if plan.mode == "manual":
                    ad.warnings.append("The logo option is on, but no logo was uploaded, so none was added.")
                return None
            await asyncio.to_thread(prepare_logo, raw, target)
            return target
        except ImageProblem as exc:
            logger.info("logo skipped: %s", exc)
            if request.logo_asset_id:
                ad.warnings.append(f"Your logo could not be used ({exc}).")
            return None

    def _overlay_spec(self, plan: AdPlan, logo: Optional[Path], brief: Optional[AdBrief] = None) -> OverlaySpec:
        """What finalize.py draws: verified text (if wanted), the logo and the QR code for the user's exact URL."""
        options, creative, facts = plan.request.options, plan.creative, plan.facts
        font = self.settings.overlay_font_path
        if creative is None:  # the original flow, unchanged: everything only when add_overlays is on
            if not options.add_overlays or facts is None:
                return OverlaySpec()
            return OverlaySpec(
                name=facts.name, offer=facts.offer, cta=facts.cta, phone=facts.phone, address=facts.address,
                qr_url=facts.website if facts.website.startswith(("http://", "https://")) else "", logo_path=logo, font_path=font,
            )
        spec = OverlaySpec(qr_url=creative.qr_url if creative.include_qr else "", logo_path=logo if creative.include_logo else None, font_path=font)
        if options.add_overlays and facts is not None:
            spec.captions = key_messages(facts, brief)
        if facts is not None:
            spec.brand_colors = list(facts.brand_colors)  # the overlay accent follows the brand, else the footage
        if options.add_overlays:
            if facts is not None:
                spec.name, spec.offer, spec.cta, spec.phone, spec.address = facts.name, _short(facts.offer) if facts.offer else "", facts.cta, facts.phone, facts.address
            else:  # manual: only what the user typed
                business = plan.request.business
                spec.name, spec.offer, spec.cta = business.name.strip(), business.offer.strip(), business.cta.strip()
                spec.phone, spec.address = business.phone.strip(), business.address.strip()
        return spec

    # ------------------------------------------------------------------ the pipeline

    async def _ticker(self, ad: AdResponse, expected_seconds: float) -> None:
        """While the video model works, move the progress bar from 50 to 85 so the page shows it is alive."""
        started = time.monotonic()
        while True:
            await asyncio.sleep(3.0)
            elapsed = time.monotonic() - started
            progress = 50 + int(35 * (1 - math.exp(-elapsed / max(1.0, expected_seconds))))
            if ad.stage != "generating_video":
                return
            ad.progress = max(ad.progress, min(progress, 85))
            await self._save(ad)

    async def _run(self, ad_id: str, plan: AdPlan) -> None:
        """Task body. Whatever happens, the ad ends as completed, completed_with_fallback or failed."""
        ad = self._active[ad_id]
        folder = self.work_dir / ad_id
        final_path = self.videos_dir / f"{ad_id}.mp4"
        started = time.monotonic()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self.videos_dir.mkdir(parents=True, exist_ok=True)
            if plan.mode == "manual":
                made = await self._make_manual(ad, plan, folder)
            elif plan.mode == "website":
                made = await self._make_website(ad, plan, folder)
            else:
                made = await self._make_ai(ad, plan, folder)

            await self._set(ad, stage="finalizing", progress=90, message="Adding your business details…", provider=made.provider)
            want_logo = plan.request.options.add_overlays if plan.creative is None else plan.creative.include_logo
            logo = await self._prepare_logo(plan, folder, ad) if want_logo else None
            spec = self._overlay_spec(plan, logo, ad.brief)
            finished = await finalize_video(made.path, final_path, spec)
            self._warn(ad, *finished.warnings)

            # never report success for a file that is not a playable video of about the planned length
            planned = sum(segment.seconds for segment in made.segments) or None
            report = await check_output(final_path, expected_seconds=planned)
            if not report.ok:
                logger.warning("ad %s failed the output check: %s", ad_id, report.problems)
                raise VideoError(f"{report.problems[0]} The ad was not published; please try again.")
            self._warn(ad, *report.warnings)
            if spec.logo_path is None and plan.creative is not None and plan.creative.include_logo and plan.mode != "manual":
                self._warn(ad, "No usable logo was found on your website, so the ad has no logo. Upload one to add it.")
            info = report

            fallback = made.fallback_used
            if fallback:
                message = "Your ad is ready, but the AI video failed: the video part is a simple clip made from your image, not AI footage." if (
                    plan.creative is not None
                ) else "Your ad is ready (demo-quality fallback)."
            else:
                message = "Your ad is ready."
            await self._set(
                ad, status="completed_with_fallback" if fallback else "completed", stage="completed", progress=100,
                fallback_used=fallback, ai_video_used=made.ai_video_used, qr_added=finished.qr_added, composition=made.segments,
                video_url=f"/api/ads/{ad_id}/video", actual_duration_seconds=max(1, round(info.duration)), message=message,
            )
        except asyncio.CancelledError:
            final_path.unlink(missing_ok=True)
            if ad_id in self._cancel_requested:
                await self._set(ad, status="failed", stage="failed", progress=100, error=CANCELLED_MESSAGE, message="The ad was cancelled.")
            else:
                await self._set(ad, status="failed", stage="failed", progress=100, error="The server is shutting down. Please try again.", message="The ad could not be finished.")
                raise
        except (VideoError, ImageProblem) as exc:
            logger.warning("ad %s failed: %s", ad_id, exc)
            final_path.unlink(missing_ok=True)
            await self._set(ad, status="failed", stage="failed", progress=100, error=str(exc), message="The ad could not be created.")
        except Exception:
            logger.exception("ad %s crashed", ad_id)
            final_path.unlink(missing_ok=True)
            await self._set(ad, status="failed", stage="failed", progress=100, error=GENERIC_ERROR, message="The ad could not be created.")
        finally:
            self._cancel_requested.discard(ad_id)
            self._prompt_ready[ad_id].set()
            self._prompt_ready.pop(ad_id, None)
            self._active.pop(ad_id, None)
            shutil.rmtree(folder, ignore_errors=True)
            logger.info("ad %s (%s) ended as %s after %.1fs (provider=%s)", ad_id, plan.mode, ad.status, time.monotonic() - started, ad.provider)

    async def _make_manual(self, ad: AdResponse, plan: AdPlan, folder: Path) -> Made:
        """Manual ad: the user's own images and videos, joined with FFmpeg. No scan, no prompt writer, no AI video."""
        assert plan.creative is not None
        options = plan.request.options
        size = output_size(options.aspect_ratio, self.settings.compose_resolution)
        await self._set(ad, status="running", stage="preparing", progress=10, message="Preparing your uploaded media…")
        frames = dict(await self._upload_frames(ad, plan, folder, options.aspect_ratio, size))
        images = sum(1 for info, _ in plan.media if info.media_type == "image")
        videos = [info for info, _ in plan.media if info.media_type == "video"]
        if videos:
            image_seconds = UPLOAD_IMAGE_SECONDS_WITH_VIDEO
            total = sum(v.duration_seconds for v in videos) + images * image_seconds
            if abs(total - options.duration_seconds) > 1:
                self._warn(ad, f"Your uploaded video keeps its full length, so the ad is about {round(total)} seconds instead of {options.duration_seconds}.")
        else:
            image_seconds = max(MIN_IMAGE_SECONDS, options.duration_seconds / max(1, images))
        segments = [
            Segment("uploaded_video", path, False, 0.0, info.asset_id) if info.media_type == "video"
            else Segment("uploaded_image", frames[info.asset_id], True, image_seconds, info.asset_id)
            for info, path in plan.media
        ]
        if videos and not plan.creative.keep_audio:
            self._warn(ad, "The sound of your video was removed, as requested (silent ad).")
        await self._set(ad, stage="composing", progress=40, message="Building your ad with FFmpeg…")
        result = await compose(
            segments, folder / "composed.mp4", size=size, style=options.style, keep_audio=plan.creative.keep_audio, work_dir=folder,
        )
        return Made(result.path, _segments(result))

    async def _make_website(self, ad: AdResponse, plan: AdPlan, folder: Path) -> Made:
        """Website ad: original website images (plus optional uploaded photos), 3 seconds each, looped to fill the length."""
        assert plan.creative is not None
        options = plan.request.options
        size = output_size(options.aspect_ratio, self.settings.compose_resolution)
        await self._set(ad, status="running", stage="preparing", progress=10, message="Downloading your website images…")
        website = [("website_image", url, path) for url, path in await self._website_frames(ad, plan.website_images, folder, options.aspect_ratio, size)]
        uploads = [("uploaded_image", asset_id, path) for asset_id, path in await self._upload_frames(ad, plan, folder, options.aspect_ratio, size)]
        pictures = website + uploads if plan.creative.prefer_website_images else uploads + website
        if not pictures:
            raise VideoError("None of the selected images could be downloaded or used, so the ad was not made. Pick other images or upload photos.")
        slots = website_slots(options.duration_seconds)
        if len(pictures) > len(slots):
            self._warn(ad, f"Each image plays for 3 seconds, so only the first {len(slots)} images fit in {options.duration_seconds} seconds.")
            pictures = pictures[:len(slots)]
        elif len(pictures) < len(slots):
            what = "the one usable image repeats" if len(pictures) == 1 else f"the {len(pictures)} images repeat in a loop"
            self._warn(ad, f"Each image plays for 3 seconds; to fill {options.duration_seconds} seconds {what}.")
        segments = []
        for index, seconds in enumerate(slots):  # one 3-second slot per image; fewer images than slots loop from the start
            kind, source, path = pictures[index % len(pictures)]
            segments.append(Segment(kind, path, True, seconds, source))
        await self._set(ad, stage="composing", progress=45, message="Building your ad from your website images…")
        result = await compose(segments, folder / "composed.mp4", size=size, style=options.style, keep_audio=False, work_dir=folder)
        return Made(result.path, _segments(result))

    async def _extra_clips(
        self, ad: AdResponse, plan: AdPlan, brief: AdBrief, hero: HeroSelection, folder: Path, missing_seconds: float,
        film_prompts: Optional[list[str]] = None,
    ) -> list[tuple[Path, float]]:
        """More AI clips from the brief's other concepts (VIDEO_CLIPS_PER_AD), so a long ad shows new footage instead of a loop.

        Stops at the first failure (the ad then loops what it has); a fallback clip is never mixed in with AI footage.
        """
        extra: list[tuple[Path, float]] = []
        film_prompts = film_prompts or []
        wanted = len(film_prompts) if film_prompts else min(max(1, self.settings.video_clips_per_ad), len(brief.concepts)) - 1
        options = plan.request.options
        for index in range(1, wanted + 1):
            if missing_seconds <= 0.5:
                break
            if film_prompts:  # the AI director's next clip of the story
                prompt = AdPrompt(
                    final_prompt=film_prompts[index - 1], positive_prompt=film_prompts[index - 1], negative_prompt="",
                    platform=options.platform, duration_seconds=plan.duration, aspect_ratio=options.aspect_ratio, shot_count=1,
                )
                title = f"story part {index + 1}"
            else:
                concept_brief = brief.model_copy(update={"chosen_concept": min(index, len(brief.concepts) - 1)})
                prompt = await self.prompts.build_scene(
                    plan.facts, options, reference=hero.reference, duration_seconds=plan.duration, loop_seconds=0, brief=concept_brief,
                )
                title = concept_brief.concept.title
            logger.info("ad %s EXTRA CLIP %s PROMPT (%s):\n%s", ad.ad_id, index + 1, title, prompt.final_prompt)
            await self._set(ad, message=f"Creating AI clip {index + 1} of {wanted + 1} ({title})…")
            request = VideoRequest(
                ad_id=f"{ad.ad_id}-{index}", prompt=prompt.final_prompt, negative_prompt=prompt.negative_prompt,
                image_path=hero.prepared.path if hero.prepared else None, duration_seconds=prompt.duration_seconds,
                aspect_ratio=prompt.aspect_ratio, resolution=self.settings.video_resolution, output_dir=folder,
                business_name=plan.facts.name if plan.facts else "",
            )
            try:
                async with self._video_slots:
                    outcome = await self.video.generate(request)
            except VideoError as exc:
                self._warn(ad, f"An extra AI clip could not be made ({exc}); the first clip is looped instead.")
                break
            if outcome.fallback_used:
                self._warn(ad, "An extra AI clip failed, so it was left out (no demo footage is mixed with AI footage).")
                break
            seconds = (await probe_media(outcome.result.path)).duration
            extra.append((outcome.result.path, seconds))
            missing_seconds -= seconds
        return extra

    async def _make_ai(self, ad: AdResponse, plan: AdPlan, folder: Path) -> Made:
        """AI ad (and the original flow): ONE prompt -> ONE AI clip, looped to the chosen length.

        ai:    text-to-video from the scraped facts only; no website picture is sent or shown.
        mixed: a website image is the first frame, and original website images open and close the ad.
        """
        request, creative, facts = plan.request, plan.creative, plan.facts
        assert facts is not None
        options = request.options
        mode = plan.mode
        target = plan.target_seconds if creative is not None else 0
        hero = HeroSelection()
        film_prompts: list[str] = []
        if mode == "ai":
            await self._set(ad, status="running", stage="preparing", progress=10, message="Collecting your business details for the AI…")
        else:
            await self._set(ad, status="running", stage="preparing", progress=10, message="Choosing the best image for your ad…")
            hero = await self._select_hero(plan, options.aspect_ratio, folder)
            self._warn(ad, *hero.warnings)

        intro: list[tuple[str, Path]] = []
        outro: list[tuple[str, Path]] = []
        if mode == "mixed":
            # prepared BEFORE the paid AI call, so a mixed ad without usable website images never spends credits
            size = output_size(options.aspect_ratio, self.settings.video_resolution)
            frames = await self._website_frames(ad, plan.website_images, folder, options.aspect_ratio, size)
            if not frames:
                raise VideoError("None of the selected website images could be downloaded, so the Website + AI ad was not made (no AI credits were used).")
            half = max(1, math.ceil(len(frames) / 2))
            intro, outro = frames[:half], (frames[half:] or frames[:1])

        if creative is None:  # the original request shape keeps its shot-list prompt
            await self._set(ad, stage="prompt_building", progress=30, message="Writing your ad prompt from your business details…")
            prompt = await self.prompts.build(facts, options, reference=hero.reference, duration_seconds=plan.duration)
        else:
            # facts -> validated Ad Brief -> ONE scene prompt; offers, prices and contacts are added later as exact text
            await self._set(ad, stage="prompt_building", progress=25, message="Planning your ad (ad brief)…")
            brief, brief_notes = await self.prompts.build_brief(
                facts, options, duration_seconds=plan.duration, include_logo=creative.include_logo, include_qr=creative.include_qr,
            )
            self._warn(ad, *brief_notes, *brief.rejected_claims)
            await self._set(ad, brief=brief, progress=32, message="Writing the video prompt from your ad brief…")
            logger.info(
                "ad %s AD BRIEF (%s): concept=%r message=%r cta=%r missing=%s rejected=%s",
                ad.ad_id, brief.builder, brief.concept.title, brief.main_message, brief.cta, brief.missing, brief.rejected_claims,
            )
            clips_wanted = min(max(1, self.settings.video_clips_per_ad), max(1, math.ceil(target / max(1, plan.duration))) if target else 1)
            film, film_notes = await self.prompts.build_film(
                facts, options, brief, clips=clips_wanted, clip_seconds=plan.duration, reference=hero.reference,
            )
            self._warn(ad, *film_notes)
            if film:  # OpenRouter wrote a shot-by-shot prose prompt for every clip
                prompt, film_prompts = film[0], [p.final_prompt for p in film[1:]]
                for index, extra in enumerate(film_prompts, start=2):
                    logger.info("ad %s FILM CLIP %s PROMPT:\n%s", ad.ad_id, index, extra)
            else:
                prompt = await self.prompts.build_scene(
                    facts, options, reference=hero.reference, duration_seconds=plan.duration, loop_seconds=target, brief=brief,
                )
        self._warn(ad, *prompt.warnings)
        # The final prompt for the video model, visible in the backend terminal for every AI ad (whatever the provider).
        logger.info(
            "ad %s FINAL VIDEO PROMPT (%s, %s chars, provider=%s):\n===== FINAL PROMPT START =====\n%s\n===== FINAL PROMPT END =====",
            ad.ad_id, prompt.builder, len(prompt.final_prompt), self.video.provider_name, prompt.final_prompt,
        )
        await self._set(ad, stage="prompt_ready", progress=45, prompt=prompt, message="Prompt ready. Creating the video…")
        self._prompt_ready[ad.ad_id].set()

        await self._set(ad, stage="generating_video", progress=50, message="Waiting for a free video slot…")
        video_request = VideoRequest(
            ad_id=ad.ad_id, prompt=prompt.final_prompt, negative_prompt=prompt.negative_prompt,
            image_path=hero.prepared.path if hero.prepared else None, duration_seconds=prompt.duration_seconds,
            aspect_ratio=prompt.aspect_ratio, resolution=self.settings.video_resolution, output_dir=folder,
            business_name=facts.name, accent_color=facts.brand_colors[0] if facts.brand_colors else "",
        )
        async with self._video_slots:
            await self._set(ad, message="Creating the AI video… this usually takes 1 to 3 minutes.")
            expected = 150.0 if self.video.provider_name != "mock" else 8.0
            ticker = asyncio.create_task(self._ticker(ad, expected))
            try:
                outcome = await self.video.generate(video_request)
            except VideoError as exc:  # keep the provider's own reason on the ad, then fail it
                ad.provider_error = str(exc)
                logger.warning("ad %s video provider failed (%s): %s", ad.ad_id, getattr(exc, "kind", "error"), exc)
                raise
            finally:
                ticker.cancel()
        self._warn(ad, *outcome.warnings)
        if outcome.provider_error:  # the fallback must not hide why the real provider failed
            ad.provider_error = outcome.provider_error
        ai_used = not outcome.fallback_used and outcome.result.provider != "mock"
        if creative is not None and outcome.fallback_used:
            self._warn(ad, "The AI video provider failed. The video part of this ad is a simple clip, NOT AI-generated footage.")
        clip_kind = "ai_video" if ai_used else "fallback_video"

        clip = await probe_media(outcome.result.path)
        if clip.duration and clip.duration < plan.duration - 0.5:
            self._warn(ad, f"The video provider returned a {clip.duration:.1f}-second clip ({plan.duration} seconds were requested).")
        clips: list[tuple[Path, float]] = [(outcome.result.path, clip.duration)]
        if creative is not None and ad.brief is not None and ai_used and target:
            clips += await self._extra_clips(ad, plan, ad.brief, hero, folder, target - clip.duration, film_prompts)
        covered = sum(seconds for _, seconds in clips)
        if creative is None or (not (intro or outro) and len(clips) == 1 and not (target and target > covered + 0.05)):
            segment = CompositionSegment(kind=clip_kind, source=outcome.result.provider, seconds=round(clip.duration, 2))
            return Made(outcome.result.path, [segment], outcome.fallback_used, ai_used, outcome.result.provider)

        # loop only what is still missing, spread over the clips (each loop repeat is reframed in compose.py)
        share = (float(target) / len(clips)) if target and target > covered + 0.05 else 0.0
        message = "Placing your website images around the AI video…" if intro else (
            f"Joining {len(clips)} AI clips…" if len(clips) > 1 else f"Looping the AI video to {target} seconds…"
        )
        await self._set(ad, stage="composing", progress=86, message=message)
        segments = [Segment("website_image", path, True, WEBSITE_IMAGE_SECONDS, url, framed=True) for url, path in intro]
        for path, seconds in clips:
            segments.append(Segment(clip_kind, path, False, 0.0, outcome.result.provider, loop_to=share if share > seconds + 0.05 else 0.0))
        segments += [Segment("website_image", path, True, WEBSITE_IMAGE_SECONDS, url, framed=True) for url, path in outro]
        result = await compose(
            segments, folder / "composed.mp4", size=(clip.width, clip.height), style=options.style, keep_audio=creative.keep_audio, work_dir=folder,
        )
        return Made(result.path, _segments(result), outcome.fallback_used, ai_used, outcome.result.provider)
