"""Magic Hour video provider (official `magic-hour` SDK, synchronous): text-to-video, or image-to-video when a first frame is given."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Callable, Optional

from ..config import Settings
from .base import VideoError, VideoRequest, VideoResult, scrub

logger = logging.getLogger(__name__)


RETRYABLE_STATUSES = {429, 502, 503, 504}  # rejected before any work started, so a retry cannot double-charge


def classify_error(exc: Exception, secret: str) -> VideoError:
    """Turn an SDK exception into a VideoError with an actionable message (the API key never appears in it)."""
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        match = re.search(r"status_code:\s*(\d{3})", str(exc))
        status = int(match.group(1)) if match else None
    detail = scrub(f"{type(exc).__name__}: {exc}", secret)
    message_match = re.search(r"'message':\s*'([^']{1,160})'", str(exc))
    reason = scrub(message_match.group(1), secret) if message_match else detail
    if status in (401, 403):
        return VideoError(
            f"Magic Hour rejected the API key (HTTP {status}). Create a new key at magichour.ai/developer, set "
            "VIDEO_MODEL_API_KEY in backend/.env and restart the backend.", kind="auth", status=status,
        )
    if status == 402:
        return VideoError("Magic Hour says the account has no credits left (HTTP 402). Add credits, then try again.", kind="credits", status=status)
    if status == 429:
        return VideoError("Magic Hour is rate limiting requests (HTTP 429). Please try again in a minute.", kind="rate_limited", retryable=True, status=status)
    if status in RETRYABLE_STATUSES:
        return VideoError(f"Magic Hour is temporarily unavailable (HTTP {status}).", kind="server", retryable=True, status=status)
    if status is not None and status >= 500:
        return VideoError(f"Magic Hour had a server error (HTTP {status}).", kind="server", status=status)
    if status is not None and 400 <= status < 500:
        return VideoError(f"Magic Hour refused the request (HTTP {status}): {reason}", kind="request", status=status)
    return VideoError("The video model failed: " + detail)


def default_client_factory(api_key: str):
    """Create the SDK client (imported lazily so the package is only needed when this provider is used)."""
    try:
        from magic_hour import Client  # type: ignore[import-not-found]
    except ImportError:
        raise VideoError("The 'magic-hour' package is not installed. Run: pip install magic-hour") from None
    return Client(token=api_key)


class MagicHourProvider:
    """Sends ONE prompt (and, when given, ONE first-frame image) to Magic Hour and waits for the finished video.

    Without an image (AI Video Priority) the footage is generated from the prompt alone (text-to-video), so no website
    picture appears in it. With an image (Website + AI Mix) it is used as the first frame (image-to-video).
    """

    name = "magic_hour"

    def __init__(self, settings: Settings, client_factory: Optional[Callable[[str], object]] = None):
        """`client_factory` lets tests inject a fake SDK client."""
        self.settings = settings
        self._factory = client_factory or default_client_factory

    async def generate(self, request: VideoRequest) -> VideoResult:
        """Submit the job in a worker thread and return the downloaded file, or raise VideoError."""
        if not self.settings.video_model_api_key:
            raise VideoError("Magic Hour needs VIDEO_MODEL_API_KEY in backend/.env.", kind="auth")
        if request.image_path is not None and not request.image_path.is_file():
            raise VideoError("The first-frame image for the video model is missing.")
        request.output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = request.output_dir / f"{request.ad_id}.mh"
        work_dir.mkdir(parents=True, exist_ok=True)
        attempts = max(0, self.settings.video_retry_attempts) + 1
        try:
            for attempt in range(1, attempts + 1):
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(self._run, request, work_dir), timeout=self.settings.video_timeout_seconds + 30
                    )
                except asyncio.TimeoutError:  # the job may still be running (and charged): never retried
                    raise VideoError("The video model took too long to answer.", kind="timeout") from None
                except VideoError as exc:
                    if not exc.retryable or attempt == attempts:
                        raise
                    delay = self.settings.video_retry_backoff_seconds * (2 ** (attempt - 1))
                    logger.warning("Magic Hour attempt %s/%s failed (%s); retrying in %.0fs", attempt, attempts, exc, delay)
                    await asyncio.sleep(delay)
            raise VideoError("The video model could not be reached.")  # pragma: no cover (the loop always returns or raises)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _run(self, request: VideoRequest, work_dir: Path) -> VideoResult:
        """Blocking SDK call (runs in a thread); the SDK waits for completion and downloads the file."""
        secret = self.settings.video_model_api_key
        client = self._factory(secret)
        seconds = max(1, min(int(request.duration_seconds), self.settings.video_max_seconds))
        common = dict(
            name=f"Ad {request.business_name or request.ad_id}"[:100],
            model=self.settings.magic_hour_model,
            end_seconds=seconds,
            resolution=request.resolution,
            wait_for_completion=True,
            download_outputs=True,
            download_directory=str(work_dir),
        )
        # The exact prompt sent to the video model (never the API key), so it can be checked in the backend terminal.
        logger.info(
            "Magic Hour %s request for ad %s (%s, %ss, %s, %s chars):\n----- PROMPT START -----\n%s\n----- PROMPT END -----",
            "text-to-video" if request.image_path is None else "image-to-video", request.ad_id, self.settings.magic_hour_model,
            seconds, request.aspect_ratio, len(request.prompt), request.prompt,
        )
        try:  # the same text in a file, in case the terminal cuts long lines: DATA_DIR/prompts/<ad_id>.txt
            prompts_dir = self.settings.data_dir / "prompts"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / f"{request.ad_id}.txt").write_text(request.prompt, encoding="utf-8")
        except OSError as exc:
            logger.warning("could not save the prompt file: %s", exc)
        try:
            if request.image_path is None:
                result = client.v1.text_to_video.generate(  # type: ignore[attr-defined]
                    style={"prompt": request.prompt}, aspect_ratio=request.aspect_ratio, **common,
                )
            else:
                result = client.v1.image_to_video.generate(  # type: ignore[attr-defined]
                    assets={"image_file_path": str(request.image_path)}, style={"prompt": request.prompt}, **common,
                )
        except VideoError:
            raise
        except Exception as exc:  # the SDK raises its own error types; never let them escape with details
            error = classify_error(exc, secret)
            logger.warning("Magic Hour call failed: %s (kind=%s, status=%s)", type(exc).__name__, error.kind, error.status)
            raise error from None
        status = str(getattr(result, "status", ""))
        if status != "complete":
            raise VideoError(f"The video model ended with status '{status or 'unknown'}'.")
        paths = [Path(p) for p in (getattr(result, "downloaded_paths", None) or [])]
        paths = [p for p in paths if p.is_file()]
        if not paths:
            raise VideoError("The video model finished but no file was downloaded.")
        final = request.output_dir / f"{request.ad_id}.raw.mp4"
        shutil.move(str(paths[0]), final)
        credits = getattr(result, "credits_charged", None)
        return VideoResult(
            path=final, provider=self.name, duration_seconds=float(seconds),
            credits_charged=float(credits) if isinstance(credits, (int, float)) else None,
        )
