"""Gemini video provider (Interactions API, Gemini Omni Flash): text-to-video, or image-to-video when a first frame is given.

`gemini-flash-latest` writes prompts. It does not generate video. The same Gemini API key calls Gemini Omni Flash,
which replaced Veo on the Gemini API.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from pathlib import Path
from typing import Optional

import httpx

from ..config import Settings
from .base import VideoError, VideoRequest, VideoResult, ffmpeg_path, run_tool, scrub

logger = logging.getLogger(__name__)

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
OMNI_ASPECTS = {"16:9", "9:16"}
OMNI_RESOLUTIONS = {"360p", "720p", "1080p", "4k"}
POLL_SECONDS = 5.0


def omni_aspect(aspect_ratio: str) -> str:
    """Omni accepts 16:9 and 9:16. Square and anything else are generated landscape and cropped afterwards."""
    cleaned = aspect_ratio.strip()
    return cleaned if cleaned in OMNI_ASPECTS else "16:9"


def omni_resolution(resolution: str) -> str:
    """Map a short-side label such as 480p onto a resolution Omni accepts."""
    cleaned = resolution.strip().lower()
    if cleaned in OMNI_RESOLUTIONS:
        return cleaned
    match = re.fullmatch(r"(\d{3,4})p", cleaned)
    if not match:
        return "720p"
    short = int(match.group(1))
    if short <= 360:
        return "360p"
    if short <= 720:
        return "720p"
    if short <= 1080:
        return "1080p"
    return "4k"


def classify_http(status: int, reason: str, secret: str) -> VideoError:
    """Turn an HTTP failure into a VideoError. The API key never appears in the message."""
    detail = scrub(reason, secret)
    lowered = detail.lower()
    if status in (401, 403) or "api key" in lowered:
        return VideoError(
            f"Gemini rejected the API key (HTTP {status}). Check GEMINI_API_KEY in backend/.env and restart the backend.",
            kind="auth", status=status,
        )
    if status == 429 and ("limit: 0" in lowered or "free tier" in lowered or "upgrade your tier" in lowered):
        return VideoError(
            "Gemini video is not included on this key's free tier. Upgrade the tier at https://ai.dev/rate-limit, then try again.",
            kind="credits", status=status,
        )
    if status == 402 or "billing" in lowered or ("quota" in lowered and status != 429):
        return VideoError("Gemini says the account has no credit left. Check billing, then try again.", kind="credits", status=status)
    if status == 429:
        return VideoError("Gemini is rate limiting requests (HTTP 429). Please try again in a minute.", kind="rate_limited", retryable=True, status=status)
    if status in {502, 503, 504}:
        return VideoError(f"Gemini is temporarily unavailable (HTTP {status}).", kind="server", retryable=True, status=status)
    if status >= 500:
        return VideoError(f"Gemini had a server error (HTTP {status}).", kind="server", status=status)
    if 400 <= status < 500:
        extra = f": {detail}" if detail else ""
        return VideoError(f"Gemini refused the request (HTTP {status}){extra}", kind="request", status=status)
    return VideoError("The video model failed: " + (detail or f"HTTP {status}"))


def video_from_payload(payload: dict) -> tuple[Optional[str], Optional[str]]:
    """Base64 video data and/or a file URI from an Interactions response."""
    data: Optional[str] = None
    uri: Optional[str] = None
    containers = []
    output = payload.get("output_video")
    if isinstance(output, dict):
        containers.append(output)
    for step in payload.get("steps") or []:
        if isinstance(step, dict):
            content = step.get("content")
            if isinstance(content, list):
                containers.extend(part for part in content if isinstance(part, dict))
            elif isinstance(content, dict):
                containers.append(content)
    for part in containers:
        if part.get("type") not in (None, "video") and "data" not in part and "uri" not in part:
            continue
        if part.get("type") not in (None, "video"):
            continue
        if isinstance(part.get("data"), str) and part["data"]:
            data = part["data"]
        if isinstance(part.get("uri"), str) and part["uri"]:
            uri = part["uri"]
        if data or uri:
            break
    return data, uri


def file_id_from_uri(uri: str) -> str:
    """The file id inside a Gemini file URI."""
    match = re.search(r"files/([^/:?]+)", uri)
    return match.group(1) if match else ""


class GeminiVideoProvider:
    """Sends ONE prompt (and, when given, ONE first-frame image) to Gemini Omni and saves the finished mp4."""

    name = "gemini"

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None):
        """An injected client is used by tests."""
        self.settings = settings
        self._client = client

    async def generate(self, request: VideoRequest) -> VideoResult:
        """Create one video, retrying only errors that happen before Gemini has accepted the job."""
        secret = self.settings.gemini_key
        if not secret:
            raise VideoError("Gemini video needs GEMINI_API_KEY in backend/.env.", kind="auth")
        if request.image_path is not None and not request.image_path.is_file():
            raise VideoError("The first-frame image for the video model is missing.")
        request.output_dir.mkdir(parents=True, exist_ok=True)
        attempts = max(0, self.settings.video_retry_attempts) + 1
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.wait_for(self._generate_once(request, secret), timeout=self.settings.video_timeout_seconds + 30)
            except asyncio.TimeoutError:
                raise VideoError("The video model took too long to answer.", kind="timeout") from None
            except VideoError as exc:
                if not exc.retryable or attempt == attempts:
                    raise
                delay = self.settings.video_retry_backoff_seconds * (2 ** (attempt - 1))
                logger.warning("Gemini attempt %s/%s failed (%s); retrying in %.0fs", attempt, attempts, exc, delay)
                await asyncio.sleep(delay)
        raise VideoError("The video model could not be reached.")  # pragma: no cover

    async def _generate_once(self, request: VideoRequest, secret: str) -> VideoResult:
        """One Interactions call, then download (and square-crop when the ad is 1:1)."""
        seconds = max(1, min(int(request.duration_seconds), self.settings.video_max_seconds))
        aspect = omni_aspect(request.aspect_ratio)
        resolution = omni_resolution(request.resolution)
        prompt = self._prompt(request, seconds)
        logger.info(
            "Gemini %s request for ad %s (%s, %ss, %s -> %s, %s, %s chars):\n----- PROMPT START -----\n%s\n----- PROMPT END -----",
            "text-to-video" if request.image_path is None else "image-to-video", request.ad_id, self.settings.gemini_video_model,
            seconds, request.aspect_ratio, aspect, resolution, len(prompt), prompt,
        )
        try:
            prompts_dir = self.settings.data_dir / "prompts"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / f"{request.ad_id}.txt").write_text(prompt, encoding="utf-8")
        except OSError as exc:
            logger.warning("could not save the prompt file: %s", exc)
        timeout = httpx.Timeout(self.settings.video_timeout_seconds, connect=10.0)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=timeout)
        try:
            payload = await self._create(client, secret, request, prompt, aspect, resolution)
            raw = await self._video_bytes(client, secret, payload)
        finally:
            if owns_client:
                await client.aclose()
        if len(raw) < 32:
            raise VideoError("The video model finished but no file was downloaded.")
        final = request.output_dir / f"{request.ad_id}.raw.mp4"
        final.write_bytes(raw)
        if request.aspect_ratio.strip() == "1:1" and aspect != "1:1":
            squared = request.output_dir / f"{request.ad_id}.square.mp4"
            await self._crop_square(final, squared)
            final.unlink(missing_ok=True)
            squared.rename(final)
        return VideoResult(path=final, provider=self.name, duration_seconds=float(seconds))

    def _prompt(self, request: VideoRequest, seconds: int) -> str:
        """The text Omni sees. Negatives go in the prompt; Omni has no separate negative-prompt field."""
        text = request.prompt.strip()
        if request.negative_prompt and "NEGATIVE PROMPT" not in text.upper():
            text = f"{text}\nDo not include: {request.negative_prompt.strip()}"
        if request.image_path is not None:
            text = "[# Sources <FIRST_FRAME>@Image1]\n" + text + "\nUse this image as the exact first frame."
        return f"Make this advertising video exactly {seconds} seconds long.\n{text}"

    def _root(self) -> str:
        """Gemini API root. A custom prompt host is used only when it is already the Gemini API."""
        base = self.settings.ai_prompt_base_url.split("/openai")[0].rstrip("/")
        if "generativelanguage.googleapis.com" in base and (base.endswith("/v1beta") or base.endswith("/v1")):
            return base
        return GEMINI_API

    def _headers(self, secret: str) -> dict[str, str]:
        """Auth header. The key is never put in the URL, so it cannot leak into access logs."""
        return {"x-goog-api-key": secret, "Content-Type": "application/json"}

    async def _create(self, client: httpx.AsyncClient, secret: str, request: VideoRequest, prompt: str, aspect: str, resolution: str) -> dict:
        """Start one video interaction and return the JSON body."""
        content: list[dict] | str
        if request.image_path is None:
            content = prompt
        else:
            mime = "image/png" if request.image_path.suffix.lower() == ".png" else "image/jpeg"
            encoded = base64.b64encode(request.image_path.read_bytes()).decode("ascii")
            content = [{"type": "image", "mime_type": mime, "data": encoded}, {"type": "text", "text": prompt}]
        body = {
            "model": self.settings.gemini_video_model,
            "input": content,
            "response_format": {"type": "video", "aspect_ratio": aspect, "resolution": resolution, "delivery": "uri"},
            "background": False,
            "stream": False,
        }
        try:
            response = await client.post(f"{self._root()}/interactions", json=body, headers=self._headers(secret))
        except httpx.TimeoutException:
            raise VideoError("The video model took too long to answer.", kind="timeout") from None
        except httpx.HTTPError as exc:
            logger.warning("Gemini connection failed: %s", type(exc).__name__)
            raise VideoError("Could not reach the video model.", kind="server", retryable=True) from None
        return self._payload(response, secret)

    def _payload(self, response: httpx.Response, secret: str) -> dict:
        """JSON body, or a VideoError when Gemini refused the call."""
        if response.status_code >= 400:
            reason = ""
            try:
                err = response.json().get("error") or {}
                if isinstance(err, dict):
                    reason = str(err.get("message") or "")
            except ValueError:
                reason = response.text[:160]
            raise classify_http(response.status_code, reason, secret)
        try:
            payload = response.json()
        except ValueError:
            raise VideoError("The video model sent an unreadable answer.") from None
        status = str(payload.get("status") or "").lower()
        if status in {"failed", "cancelled", "error"}:
            reason = str(payload.get("error") or status)
            raise VideoError(f"The video model ended with status '{scrub(reason, secret) or status}'.", kind="server")
        return payload

    async def _video_bytes(self, client: httpx.AsyncClient, secret: str, payload: dict) -> bytes:
        """Inline video bytes, or a download after the file URI becomes ready."""
        deadline = time.monotonic() + self.settings.video_timeout_seconds
        current = payload
        while True:
            data, uri = video_from_payload(current)
            if data:
                try:
                    return base64.b64decode(data, validate=False)
                except (ValueError, TypeError):
                    raise VideoError("The video model sent a video that could not be read.") from None
            if uri:
                file_id = file_id_from_uri(uri)
                if file_id:
                    await self._wait_until_active(client, secret, file_id, deadline)
                    return await self._download(client, secret, file_id)
                return await self._download_uri(client, secret, uri)
            status = str(current.get("status") or "").lower()
            interaction_id = str(current.get("id") or "")
            if status in {"completed", "complete"} or not interaction_id or time.monotonic() >= deadline:
                raise VideoError("The video model finished but no file was downloaded.")
            await asyncio.sleep(POLL_SECONDS)
            current = await self._get_interaction(client, secret, interaction_id)

    async def _get_interaction(self, client: httpx.AsyncClient, secret: str, interaction_id: str) -> dict:
        """Poll one interaction."""
        try:
            response = await client.get(f"{self._root()}/interactions/{interaction_id}", headers=self._headers(secret))
        except httpx.HTTPError:
            raise VideoError("Could not reach the video model.", kind="server", retryable=True) from None
        return self._payload(response, secret)

    async def _wait_until_active(self, client: httpx.AsyncClient, secret: str, file_id: str, deadline: float) -> None:
        """Poll the Files API until the generated video can be downloaded."""
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"{self._root()}/files/{file_id}", headers=self._headers(secret))
            except httpx.HTTPError:
                raise VideoError("Could not reach the video model.", kind="server", retryable=True) from None
            if response.status_code >= 400:
                self._payload(response, secret)
            try:
                state = str((response.json() or {}).get("state") or "").upper()
            except ValueError:
                state = ""
            if state == "ACTIVE":
                return
            if state == "FAILED":
                raise VideoError("Gemini could not finish the video.", kind="server")
            await asyncio.sleep(POLL_SECONDS)
        raise VideoError("The video model took too long to answer.", kind="timeout")

    async def _download(self, client: httpx.AsyncClient, secret: str, file_id: str) -> bytes:
        """Download a finished file by id."""
        url = f"{self._root()}/files/{file_id}:download?alt=media"
        return await self._download_uri(client, secret, url)

    async def _download_uri(self, client: httpx.AsyncClient, secret: str, uri: str) -> bytes:
        """Download video bytes. The API key stays in the header."""
        try:
            response = await client.get(uri, headers={"x-goog-api-key": secret}, follow_redirects=True)
        except httpx.HTTPError:
            raise VideoError("Could not download the finished video.", kind="server", retryable=True) from None
        if response.status_code >= 400:
            raise classify_http(response.status_code, "", secret)
        return response.content

    async def _crop_square(self, source: Path, dest: Path) -> None:
        """Center-crop a landscape Omni clip to the square frame Facebook ads use."""
        await run_tool(
            [
                ffmpeg_path(), "-y", "-i", str(source),
                "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dest),
            ],
            timeout=120,
        )
