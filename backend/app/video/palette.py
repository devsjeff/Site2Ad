"""Overlay colours that follow the video: sample a few frames, then pick an accent and panel tint that fit them.

- Accent (bar, CTA pill, caption underline): the brand colour when the website has a usable one, otherwise the most
  vivid colour that is actually in the footage, normalised so it reads well on screen.
- Panel tint: a very dark, see-through version of the accent hue, so the panel belongs to the picture instead of
  covering it. Where the footage behind the text is very bright the panel gets a little more opacity, so the text
  always keeps enough contrast (it also carries a soft outline).
- Text on the accent (the CTA label): dark on light accents, white on dark ones.
"""

from __future__ import annotations

import colorsys
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageStat

from .base import VideoError, ffmpeg_path, run_tool

logger = logging.getLogger(__name__)

RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class Palette:
    """Colours for every overlay element."""

    accent: RGBA = (255, 196, 0, 255)
    accent_text: RGBA = (20, 20, 24, 255)
    highlight: RGBA = (255, 214, 102, 255)  # the accent hue, light enough to read as TEXT over any footage
    text: RGBA = (255, 255, 255, 255)
    soft_text: RGBA = (232, 232, 238, 255)
    panel: tuple[int, int, int] = (14, 14, 20)
    panel_alpha_start: int = 140  # left edge of the panel
    panel_alpha_end: int = 40  # right edge: the panel fades into the picture
    caption_alpha: int = 95
    outline: RGBA = (0, 0, 0, 150)


DEFAULT_PALETTE = Palette()


def _hex(value: str) -> tuple[int, int, int] | None:
    """'#rrggbb' -> (r, g, b)."""
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
    if not match:
        return None
    raw = match.group(1)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _hls(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """RGB 0-255 -> HLS 0-1."""
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def _rgb(h: float, lightness: float, saturation: float) -> tuple[int, int, int]:
    """HLS 0-1 -> RGB 0-255."""
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, lightness, saturation))  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Relative brightness 0-1."""
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def vivid(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """The same hue, made bright and saturated enough to work as a UI accent on video."""
    h, lightness, s = _hls(rgb)
    return _rgb(h, min(0.62, max(0.5, lightness)), max(0.7, s))


def footage_accent(images: list[Image.Image]) -> tuple[int, int, int] | None:
    """The most vivid colour that occupies a real part of the frames (weighted by area and saturation)."""
    best, best_score = None, 0.0
    for image in images:
        small = image.convert("RGB").resize((96, 54))
        quantized = small.quantize(colors=8)
        palette = quantized.getpalette() or []
        for count, index in quantized.getcolors() or []:
            rgb = tuple(palette[index * 3: index * 3 + 3])
            if len(rgb) < 3:
                continue
            _, lightness, saturation = _hls(rgb)  # type: ignore[arg-type]
            if lightness < 0.15 or lightness > 0.9 or saturation < 0.25:
                continue
            score = count * saturation * saturation
            if score > best_score:
                best, best_score = rgb, score
    return best  # type: ignore[return-value]


def region_brightness(images: list[Image.Image], box: tuple[float, float, float, float]) -> float:
    """Average brightness 0-1 of a region (fractions of width/height) across the frames."""
    values = []
    for image in images:
        w, h = image.size
        crop = image.convert("L").crop((round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h)))
        values.append(ImageStat.Stat(crop).mean[0] / 255)
    return sum(values) / len(values) if values else 0.4


def palette_from_frames(images: list[Image.Image], brand_colors: list[str] | None = None) -> Palette:
    """Pick the overlay colours for this footage (see the module docstring)."""
    base = None
    for value in brand_colors or []:
        rgb = _hex(value)
        if rgb and _hls(rgb)[2] >= 0.25 and 0.12 < _hls(rgb)[1] < 0.92:
            base = rgb
            break
    if base is None and images:
        base = footage_accent(images)
    if base is None:
        return DEFAULT_PALETTE
    accent = vivid(base)
    hue = _hls(accent)[0]
    panel = _rgb(hue, 0.08, 0.35)
    lower = region_brightness(images, (0.0, 0.55, 0.65, 1.0)) if images else 0.4
    upper = region_brightness(images, (0.1, 0.0, 0.9, 0.3)) if images else 0.4
    return Palette(
        accent=(*accent, 255),
        highlight=(*_rgb(hue, 0.76, 0.9), 255),
        accent_text=(20, 20, 24, 255) if _luminance(accent) > 0.55 else (255, 255, 255, 255),
        panel=panel,
        panel_alpha_start=175 if lower > 0.62 else 140,
        panel_alpha_end=70 if lower > 0.62 else 40,
        caption_alpha=125 if upper > 0.62 else 95,
    )


async def sample_frames(src: Path, duration: float, folder: Path, count: int = 3) -> list[Image.Image]:
    """A few small frames spread over the video (start, middle, end) for colour analysis. Empty list on failure."""
    folder.mkdir(parents=True, exist_ok=True)
    images: list[Image.Image] = []
    for index in range(count):
        at = max(0.0, duration * (index + 0.5) / count)
        out = folder / f"sample-{index}.png"
        try:
            await run_tool([ffmpeg_path(), "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=192:-2", str(out)], timeout=30)
            with Image.open(out) as frame:
                images.append(frame.convert("RGB").copy())
        except (VideoError, OSError) as exc:
            logger.info("frame sample at %.1fs failed: %s", at, exc)
        finally:
            out.unlink(missing_ok=True)
    return images
