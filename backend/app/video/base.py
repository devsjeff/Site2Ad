"""Shared video types: the provider interface, request/result objects, errors and a few helpers."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from .. import catalog


class VideoError(Exception):
    """A video step failed. The message is safe to show to the user (no keys, no stack traces).

    `kind` says what went wrong (auth, credits, request, rate_limited, server, timeout, error); `retryable` marks
    transient provider errors that may succeed when tried again; `status` is the provider's HTTP status, if any.
    """

    def __init__(self, message: str, *, kind: str = "error", retryable: bool = False, status: Optional[int] = None):
        """Keep the classification next to the message."""
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status = status


@dataclass
class VideoRequest:
    """Everything a provider needs to make ONE video."""

    ad_id: str
    prompt: str  # the full prompt, including the NEGATIVE PROMPT section
    negative_prompt: str
    image_path: Optional[Path]  # the ONE hero image (first frame), already cropped to the aspect ratio
    duration_seconds: int
    aspect_ratio: str
    resolution: str
    output_dir: Path
    business_name: str = ""
    accent_color: str = ""


@dataclass
class VideoResult:
    """A finished raw video file."""

    path: Path
    provider: str
    duration_seconds: float = 0.0
    credits_charged: Optional[float] = None


class VideoProvider(Protocol):
    """Anything that turns a VideoRequest into a video file."""

    name: str

    async def generate(self, request: VideoRequest) -> VideoResult:
        """Create the video or raise VideoError."""
        ...


def output_size(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    """Pixel size (width, height) for an aspect ratio and a resolution like '480p' (short side), both even numbers."""
    match = re.fullmatch(r"(\d{3,4})p", resolution.strip().lower())
    short = int(match.group(1)) if match else 480
    w, h = catalog.parse_aspect(aspect_ratio)
    if w >= h:
        height, width = short, short * w / h
    else:
        width, height = short, short * h / w
    return max(2, round(width / 2) * 2), max(2, round(height / 2) * 2)


def scrub(text: str, *secrets: str) -> str:
    """Remove secrets and control characters from an error message and cut it short."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240]


def ffmpeg_path() -> str:
    """Path of the ffmpeg binary, or raise VideoError with install help."""
    path = shutil.which("ffmpeg")
    if not path:
        raise VideoError("FFmpeg is not installed on the server. Install it (see README) to create videos.")
    return path


async def run_tool(args: list[str], timeout: float) -> tuple[str, str]:
    """Run a command without a shell; kill it on timeout. Returns (stdout, stderr) or raises VideoError."""
    try:
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as exc:
        raise VideoError(f"Could not start {Path(args[0]).name}: {exc.strerror or exc}") from None
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise VideoError(f"{Path(args[0]).name} took too long and was stopped.") from None
    except asyncio.CancelledError:  # the ad was cancelled or the server is stopping: never leave ffmpeg running
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode != 0:
        tail = err.decode("utf-8", errors="replace").strip().splitlines()[-1:] or ["unknown error"]
        raise VideoError(f"{Path(args[0]).name} failed: {scrub(tail[0])}")
    return out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


@dataclass
class VideoInfo:
    """Basic facts about a video file."""

    width: int
    height: int
    duration: float


async def probe_video(path: Path) -> VideoInfo:
    """Read width, height and duration with ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise VideoError("ffprobe is not installed on the server (it comes with FFmpeg).")
    out, _ = await run_tool(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)],
        timeout=30,
    )
    try:
        data = json.loads(out)
        stream = data["streams"][0]
        return VideoInfo(int(stream["width"]), int(stream["height"]), float(data.get("format", {}).get("duration") or 0.0))
    except (ValueError, KeyError, IndexError, TypeError):
        raise VideoError("The video file could not be read.") from None


@dataclass
class MediaInfo:
    """What ffprobe found in a media file: the first video stream, whether there is sound, and the container."""

    width: int
    height: int
    duration: float
    video_codec: str
    has_audio: bool
    format_name: str


async def probe_media(path: Path) -> MediaInfo:
    """Read the video stream, audio presence, duration and container with ffprobe. Raises VideoError when there is no video."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise VideoError("ffprobe is not installed on the server (it comes with FFmpeg).")
    out, _ = await run_tool(
        [
            ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration,format_name",
            "-of", "json", str(path),
        ],
        timeout=30,
    )
    try:
        data = json.loads(out)
        streams = data.get("streams") or []
        video = next(s for s in streams if s.get("codec_type") == "video")
        fmt = data.get("format") or {}
        return MediaInfo(
            width=int(video["width"]), height=int(video["height"]), duration=float(fmt.get("duration") or 0.0),
            video_codec=str(video.get("codec_name") or ""), has_audio=any(s.get("codec_type") == "audio" for s in streams),
            format_name=str(fmt.get("format_name") or ""),
        )
    except (StopIteration, ValueError, KeyError, TypeError):
        raise VideoError("The file does not contain a readable video.") from None
