"""Final step: burn verified text, logo and QR code onto the generated video with Pillow + ffmpeg.

Video models draw digits and letters badly, so the business name, offer, call to action, phone and address are added
here instead, from facts that were scraped or typed by the user. Missing facts are simply left out.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .base import VideoError, ffmpeg_path, probe_video, run_tool

logger = logging.getLogger(__name__)

BOLD_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)
REGULAR_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial.ttf",
)
# scripts DejaVu cannot draw: (regex of characters, bold font paths, regular font paths)
SCRIPT_FONTS = (
    (re.compile(r"[\u0900-\u097F]"), ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",), ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",)),
    (re.compile(r"[\u0600-\u06FF]"), ("/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",), ("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",)),
    (re.compile(r"[\u0B80-\u0BFF]"), ("/usr/share/fonts/truetype/noto/NotoSansTamil-Bold.ttf",), ("/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf",)),
)
QR_WARNING_PREFIX = "QR code"  # every warning about a skipped QR code starts with this
TEXT_COLOR = (255, 255, 255, 255)
ACCENT_COLOR = (255, 214, 102, 255)


@dataclass
class OverlaySpec:
    """What to put on the video. Empty values are skipped."""

    name: str = ""
    offer: str = ""
    cta: str = ""
    phone: str = ""
    address: str = ""
    qr_url: str = ""
    logo_path: Optional[Path] = None
    font_path: str = ""  # optional TTF used for all text (OVERLAY_FONT_PATH)

    @property
    def has_any(self) -> bool:
        """True when there is anything to draw."""
        return any([self.name.strip(), self.offer.strip(), self.cta.strip(), self.phone.strip(), self.address.strip(), self.qr_url.strip(), self.logo_path])


@dataclass
class FinalizeResult:
    """Outcome of the overlay step. `applied` is False when the raw video was kept."""

    path: Path
    applied: bool
    warnings: list[str] = field(default_factory=list)
    qr_added: bool = False  # True only when a QR code was really burned into the video


def _first_existing(paths: tuple[str, ...]) -> Optional[str]:
    """First font file that exists."""
    for candidate in paths:
        if Path(candidate).is_file():
            return candidate
    return None


def load_font(size: int, bold: bool, sample: str = "", override: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A font for the text: the configured file, a script-specific one when needed, else DejaVu/Liberation/Arial, else Pillow's default."""
    if override and Path(override).is_file():
        try:
            return ImageFont.truetype(override, size)
        except OSError:
            pass
    for pattern, bold_paths, regular_paths in SCRIPT_FONTS:
        if pattern.search(sample):
            path = _first_existing(bold_paths if bold else regular_paths)
            if path:
                return ImageFont.truetype(path, size)
    path = _first_existing(BOLD_FONTS if bold else REGULAR_FONTS)
    try:
        if path:
            return ImageFont.truetype(path, size)
        return ImageFont.load_default(size)
    except (OSError, TypeError):
        return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, line: str, font, max_width: int) -> str:
    """Shorten one line with an ellipsis until it fits the pixel width."""
    while len(line) > 1 and draw.textlength(line, font=font) > max_width:
        line = line[:-2].rstrip() + "…"
    return line


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    """Wrap text to a pixel width; if more than max_lines are needed the last line is cut with an ellipsis."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for index, word in enumerate(words):
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            current = " ".join(words[index:])
            break
    if current:
        lines.append(current)
    return [_fit(draw, line, font, max_width) for line in lines[:max_lines]]


class QrUnavailable(Exception):
    """The QR code could not be made; the message says why."""


def _make_qr(url: str):
    """A PIL image of a QR code for exactly `url` (default 4-module quiet zone). Raises QrUnavailable."""
    try:
        import qrcode  # type: ignore[import-not-found]
    except ImportError:
        raise QrUnavailable(f"{QR_WARNING_PREFIX} skipped because the 'qrcode' package is not installed.") from None
    try:
        return qrcode.make(url).convert("RGBA")
    except Exception as exc:  # e.g. data too long for a QR code
        logger.warning("QR code generation failed: %r", exc)
        raise QrUnavailable(f"{QR_WARNING_PREFIX} skipped because it could not be generated for that address.") from None


def render_overlay(width: int, height: int, spec: OverlaySpec, out_path: Path) -> list[str]:
    """Draw the transparent overlay PNG for a video of this size. Returns warnings about anything skipped."""
    warnings: list[str] = []
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    unit = min(width, height)
    margin = max(12, round(unit * 0.04))
    pad = max(10, round(unit * 0.03))
    gap = max(6, round(unit * 0.012))

    qr_size = 0
    qr_image = None
    if spec.qr_url.strip():
        try:
            qr_image = _make_qr(spec.qr_url.strip())
            qr_size = max(96, round(unit * 0.24))
        except QrUnavailable as exc:
            warnings.append(str(exc))

    entries: list[tuple[str, bool, int, tuple[int, int, int, int]]] = []  # (text, bold, size, colour)
    if spec.name.strip():
        entries.append((spec.name.strip(), True, round(unit * 0.062), TEXT_COLOR))
    if spec.offer.strip():
        entries.append((spec.offer.strip(), True, round(unit * 0.047), ACCENT_COLOR))
    if spec.cta.strip():
        entries.append((spec.cta.strip(), True, round(unit * 0.045), TEXT_COLOR))
    if spec.phone.strip():
        entries.append((spec.phone.strip(), False, round(unit * 0.045), TEXT_COLOR))
    if spec.address.strip():
        entries.append((spec.address.strip(), False, round(unit * 0.036), TEXT_COLOR))

    if entries:
        right_limit = width - margin - (qr_size + gap * 2 if qr_size else 0)
        panel_max = max(120, min(right_limit - margin, round(width * 0.62 if qr_size else width * 0.8)))
        text_width = panel_max - 2 * pad
        blocks: list[tuple[list[str], object, tuple[int, int, int, int], int]] = []
        for text, bold, size, colour in entries:
            font = load_font(max(12, size), bold, text, spec.font_path)
            lines = wrap_text(draw, text, font, text_width, 3 if bold else 2)
            line_height = round(max(12, size) * 1.25)
            blocks.append((lines, font, colour, line_height))
        used_width = max(draw.textlength(line, font=font) for lines, font, _, _ in blocks for line in lines)
        panel_width = min(panel_max, round(used_width) + 2 * pad)
        panel_height = 2 * pad + sum(len(lines) * lh for lines, _, _, lh in blocks) + gap * (len(blocks) - 1)
        x, y = margin, height - margin - panel_height
        draw.rounded_rectangle((x, y, x + panel_width, y + panel_height), radius=max(8, pad // 2), fill=(0, 0, 0, 175))
        cursor = y + pad
        for lines, font, colour, line_height in blocks:
            for line in lines:
                draw.text((x + pad, cursor), line, font=font, fill=colour)
                cursor += line_height
            cursor += gap

    if qr_image is not None:
        qr = qr_image.resize((qr_size, qr_size), Image.Resampling.NEAREST)
        qx, qy = width - margin - qr_size, height - margin - qr_size
        backing = max(6, round(unit * 0.012))
        draw.rounded_rectangle((qx - backing, qy - backing, qx + qr_size + backing, qy + qr_size + backing), radius=8, fill=(255, 255, 255, 255))
        canvas.alpha_composite(qr, (qx, qy))

    if spec.logo_path:
        try:
            with Image.open(spec.logo_path) as raw:
                logo = raw.convert("RGBA")
            logo.thumbnail((round(width * 0.22), round(height * 0.14)), Image.Resampling.LANCZOS)
            backing = max(6, round(unit * 0.015))
            draw.rounded_rectangle(
                (margin, margin, margin + logo.width + 2 * backing, margin + logo.height + 2 * backing), radius=10, fill=(255, 255, 255, 215)
            )
            canvas.alpha_composite(logo, (margin + backing, margin + backing))
        except (OSError, ValueError):
            warnings.append("The logo could not be read and was skipped.")

    canvas.save(out_path)
    return warnings


async def finalize_video(src: Path, dst: Path, spec: OverlaySpec, *, timeout: float = 180.0) -> FinalizeResult:
    """Overlay `spec` on `src` and write `dst`. On any problem the raw video is copied to `dst` and a warning is returned."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not spec.has_any:
        _copy(src, dst)
        return FinalizeResult(dst, False)
    try:
        info = await probe_video(src)
        overlay = dst.with_suffix(".overlay.png")
        warnings = await asyncio.to_thread(render_overlay, info.width, info.height, spec, overlay)
        temp = dst.with_suffix(".tmp.mp4")
        try:
            await run_tool(
                [
                    ffmpeg_path(), "-y", "-loglevel", "error", "-i", str(src), "-i", str(overlay),
                    "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]",
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-movflags", "+faststart", str(temp),
                ],
                timeout=timeout,
            )
            temp.replace(dst)
        finally:
            overlay.unlink(missing_ok=True)
            temp.unlink(missing_ok=True)
        qr_added = bool(spec.qr_url.strip()) and not any(w.startswith(QR_WARNING_PREFIX) for w in warnings)
        return FinalizeResult(dst, True, warnings, qr_added=qr_added)
    except (VideoError, OSError, ValueError) as exc:
        logger.warning("overlay step failed, keeping the raw video: %s", exc)
        _copy(src, dst)
        warnings = [f"Text overlays could not be added ({exc}); the video is shown without them."]
        if spec.qr_url.strip():
            warnings.append(f"{QR_WARNING_PREFIX} was not added because the overlay step failed.")
        return FinalizeResult(dst, False, warnings)


def _copy(src: Path, dst: Path) -> None:
    """Copy a file unless it is already in place."""
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)


if __name__ == "__main__":  # tiny manual check: python -m app.video.finalize in.mp4 out.mp4 "Name"
    if len(sys.argv) >= 4:
        result = asyncio.run(finalize_video(Path(sys.argv[1]), Path(sys.argv[2]), OverlaySpec(name=sys.argv[3])))
        print(result)
