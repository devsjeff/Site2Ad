"""Offline demo provider: turns the hero image into a slow zoom video with ffmpeg. No API key, no credits.

It is used when no video key is configured (so the whole product can be tried for free) and as the fallback when the
real video model fails.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import Settings
from .base import VideoError, VideoRequest, VideoResult, ffmpeg_path, output_size, run_tool

logger = logging.getLogger(__name__)

FPS = 24
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A bold scalable font if the machine has one, else Pillow's built-in scalable default."""
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # very old Pillow: fixed-size bitmap font
        return ImageFont.load_default()


def _hex_to_rgb(value: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    """Convert '#rrggbb' to a tuple, or return the default."""
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
    if not match:
        return default
    raw = match.group(1)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def render_still(request: VideoRequest, size: tuple[int, int], out_path: Path) -> None:
    """Draw the first frame: the hero image, or (without one) a simple gradient with the business name."""
    width, height = size
    if request.image_path and request.image_path.is_file():
        with Image.open(request.image_path) as source:
            image = source.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    else:
        base = _hex_to_rgb(request.accent_color, (38, 70, 120))
        image = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(image)
        for y in range(height):  # vertical gradient to black
            shade = 1 - 0.65 * (y / height)
            draw.line([(0, y), (width, y)], fill=tuple(int(c * shade) for c in base))
        font = load_font(max(24, width // 12))
        text = request.business_name or "Your business"
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((width - (box[2] - box[0])) / 2, (height - (box[3] - box[1])) / 2), text, font=font, fill=(255, 255, 255))
    image.save(out_path, "PNG")


class MockVideoProvider:
    """Creates a gentle zoom video from the hero image with ffmpeg."""

    name = "mock"

    def __init__(self, settings: Settings):
        """Keep settings (resolution is taken from the request)."""
        self.settings = settings

    async def generate(self, request: VideoRequest) -> VideoResult:
        """Render the still, then let ffmpeg's zoompan make the motion."""
        ffmpeg = ffmpeg_path()
        width, height = output_size(request.aspect_ratio, request.resolution)
        duration = max(1, int(request.duration_seconds))
        frames = duration * FPS
        request.output_dir.mkdir(parents=True, exist_ok=True)
        still = request.output_dir / f"{request.ad_id}.still.png"
        out = request.output_dir / f"{request.ad_id}.raw.mp4"
        # draw at 2x so the zoom stays smooth (zoompan on small inputs jitters)
        await asyncio.to_thread(render_still, request, (width * 2, height * 2), still)
        zoom = f"zoompan=z='min(1+0.0009*on,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={FPS},format=yuv420p"
        args = [
            ffmpeg, "-y", "-loglevel", "error", "-i", str(still), "-vf", zoom, "-frames:v", str(frames),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", str(out),
        ]
        try:
            await run_tool(args, timeout=max(60.0, duration * 6.0))
        finally:
            still.unlink(missing_ok=True)
        if not out.is_file() or out.stat().st_size == 0:
            raise VideoError("The demo video could not be created.")
        return VideoResult(path=out, provider=self.name, duration_seconds=float(duration))
