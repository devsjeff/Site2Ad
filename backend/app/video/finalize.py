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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .base import VideoError, ffmpeg_path, probe_video, run_tool
from .palette import DEFAULT_PALETTE, Palette, palette_from_frames, sample_frames

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
    captions: list[str] = field(default_factory=list)  # short verified messages shown one after another (top of the frame)
    brand_colors: list[str] = field(default_factory=list)  # website colours; the first usable one becomes the accent
    palette: Optional[Palette] = None  # set by finalize_video from the footage; None = defaults
    font_path: str = ""  # optional TTF used for all text (OVERLAY_FONT_PATH)

    @property
    def has_any(self) -> bool:
        """True when there is anything to draw."""
        return any([
            self.name.strip(), self.offer.strip(), self.cta.strip(), self.phone.strip(), self.address.strip(), self.qr_url.strip(),
            self.logo_path, any(c.strip() for c in self.captions),
        ])


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


PANEL_FILL = (12, 12, 16, 205)
SOFT_TEXT = (225, 225, 230, 255)
CTA_TEXT = (20, 20, 24, 255)


@dataclass
class OverlayLayer:
    """One overlay element: its own small transparent PNG, where it sits, and how it animates in."""

    kind: str  # logo | panel | qr | cta
    path: Path
    x: int
    y: int
    start: float  # seconds after the start of the video
    duration: float
    dx: int = 0  # starts this far to the LEFT of its place and eases in
    dy: int = 0  # starts this far BELOW (positive) or ABOVE (negative) its place
    end: Optional[float] = None  # fades out from here (captions); None = stays to the end
    motion: str = "ease"  # ease | overshoot | spring
    attention_at: Optional[float] = None  # a small bounce at this time to pull the eye back (CTA near the end)


def _text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill, palette: Palette, size: int) -> None:
    """Text with a soft dark outline, readable on any footage even over a see-through panel."""
    draw.text(xy, text, font=font, fill=fill, stroke_width=max(1, round(size / 22)), stroke_fill=palette.outline)


def _gradient_panel(width: int, height: int, palette: Palette, radius: int) -> Image.Image:
    """A rounded panel tinted with the accent hue that fades from left to right, so the video shows through."""
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    ramp = Image.linear_gradient("L").rotate(-90, expand=True).resize((width, height))  # 255 at the left, 0 at the right
    alpha = ramp.point(lambda v: round(palette.panel_alpha_end + (palette.panel_alpha_start - palette.panel_alpha_end) * v / 255))
    panel = Image.new("RGBA", (width, height), (*palette.panel, 0))
    panel.putalpha(ImageChops.multiply(alpha, mask))
    return panel


def _save_layer(image: Image.Image, folder: Path, kind: str) -> Path:
    """Write one layer PNG."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"layer-{kind}.png"
    image.save(path)
    return path


def render_layers(
    width: int, height: int, spec: OverlaySpec, folder: Path, duration: float = 0.0,
) -> tuple[list[OverlayLayer], list[str]]:
    """Draw each overlay element as its own layer (logo top-left, text panel bottom-left, QR bottom-right, CTA pill)."""
    warnings: list[str] = []
    layers: list[OverlayLayer] = []
    palette = spec.palette or DEFAULT_PALETTE
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    unit = min(width, height)
    margin = max(12, round(unit * 0.04))
    pad = max(10, round(unit * 0.03))
    gap = max(6, round(unit * 0.012))
    bar = max(4, round(unit * 0.012))

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
        entries.append((spec.name.strip(), True, round(unit * 0.066), palette.text))
    if spec.offer.strip():
        entries.append((spec.offer.strip(), True, round(unit * 0.047), palette.highlight))
    if spec.phone.strip():
        entries.append((spec.phone.strip(), False, round(unit * 0.040), palette.soft_text))
    if spec.address.strip():
        entries.append((spec.address.strip(), False, round(unit * 0.034), palette.soft_text))
    cta = spec.cta.strip()

    if entries or cta:
        right_limit = width - margin - (qr_size + gap * 3 if qr_size else 0)
        panel_max = max(140, min(right_limit - margin, round(width * 0.62 if qr_size else width * 0.8)))
        text_width = panel_max - 2 * pad - bar
        blocks: list[tuple[list[str], object, tuple[int, int, int, int], int, int]] = []
        for text_value, bold, size, colour in entries:
            font = load_font(max(12, size), bold, text_value, spec.font_path)
            lines = wrap_text(measure, text_value, font, text_width, 2 if bold else 2)
            blocks.append((lines, font, colour, round(max(12, size) * 1.22), max(12, size)))
        cta_font = load_font(max(12, round(unit * 0.044)), True, cta, spec.font_path)
        cta_text = _fit(measure, cta, cta_font, text_width - 2 * pad) if cta else ""
        cta_w = round(measure.textlength(cta_text, font=cta_font)) + 2 * pad if cta else 0
        cta_h = round(max(12, unit * 0.044) * 1.9) if cta else 0
        widths = [measure.textlength(line, font=font) for lines, font, _, _, _ in blocks for line in lines] + [cta_w - pad]
        panel_w = min(panel_max, round(max(widths)) + 2 * pad + bar + pad)
        text_h = sum(len(lines) * lh for lines, _, _, lh, _ in blocks) + gap * max(0, len(blocks) - 1)
        panel_h = 2 * pad + text_h + (gap + cta_h if cta else 0)
        panel = _gradient_panel(panel_w, panel_h, palette, max(10, pad // 2))
        draw = ImageDraw.Draw(panel)
        draw.rounded_rectangle((0, 0, bar, panel_h - 1), radius=bar // 2, fill=palette.accent)
        cursor = pad
        for lines, font, colour, line_height, size in blocks:
            for line in lines:
                _text(draw, (bar + pad, cursor), line, font, colour, palette, size)
                cursor += line_height
            cursor += gap
        panel_x, panel_y = margin, height - margin - panel_h
        layers.append(OverlayLayer("panel", _save_layer(panel, folder, "panel"), panel_x, panel_y, 0.35, 0.7, dx=round(panel_w * 0.3), motion="overshoot"))
        if cta:
            pill = Image.new("RGBA", (cta_w, cta_h), (0, 0, 0, 0))
            pill_draw = ImageDraw.Draw(pill)
            pill_draw.rounded_rectangle((0, 0, cta_w - 1, cta_h - 1), radius=cta_h // 2, fill=palette.accent)
            box = pill_draw.textbbox((0, 0), cta_text, font=cta_font)
            pill_draw.text(((cta_w - (box[2] - box[0])) / 2 - box[0], (cta_h - (box[3] - box[1])) / 2 - box[1]), cta_text, font=cta_font, fill=palette.accent_text)
            cta_y = panel_y + panel_h - pad - cta_h
            layers.append(OverlayLayer(
                "cta", _save_layer(pill, folder, "cta"), panel_x + bar + pad, cta_y, 1.1, 0.5, dy=round(unit * 0.05), motion="spring",
                attention_at=duration - 3.0 if duration >= 6 else None,
            ))

    if qr_image is not None:
        backing = max(6, round(unit * 0.012))
        tile = Image.new("RGBA", (qr_size + 2 * backing, qr_size + 2 * backing), (0, 0, 0, 0))
        ImageDraw.Draw(tile).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius=8, fill=(255, 255, 255, 255))
        tile.alpha_composite(qr_image.resize((qr_size, qr_size), Image.Resampling.NEAREST), (backing, backing))
        qx, qy = width - margin - qr_size - backing, height - margin - qr_size - backing
        layers.append(OverlayLayer("qr", _save_layer(tile, folder, "qr"), qx, qy, 0.7, 0.55, dy=round(unit * 0.06), motion="spring"))

    if spec.logo_path:
        try:
            with Image.open(spec.logo_path) as raw:
                logo = raw.convert("RGBA")
            logo.thumbnail((round(width * 0.22), round(height * 0.14)), Image.Resampling.LANCZOS)
            backing = max(6, round(unit * 0.015))
            tile = Image.new("RGBA", (logo.width + 2 * backing, logo.height + 2 * backing), (0, 0, 0, 0))
            ImageDraw.Draw(tile).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius=10, fill=(255, 255, 255, 215))
            tile.alpha_composite(logo, (backing, backing))
            layers.append(OverlayLayer("logo", _save_layer(tile, folder, "logo"), margin, margin, 0.2, 0.55, dy=-round(unit * 0.04), motion="spring"))
        except (OSError, ValueError):
            warnings.append("The logo could not be read and was skipped.")
    if spec.captions:
        layers += _caption_layers(width, height, spec, folder, unit, margin, pad, duration)
    return layers, warnings


CAPTION_SECONDS = 2.6
CAPTION_FIRST_START = 0.5


def _caption_layers(
    width: int, height: int, spec: OverlaySpec, folder: Path, unit: int, margin: int, pad: int, duration: float = 0.0,
) -> list[OverlayLayer]:
    """One layer per caption, top-centre, each sliding up in turn and fading out before the next (the ad 'speaks' visually)."""
    layers: list[OverlayLayer] = []
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_width = round(width * 0.82)
    for index, caption in enumerate(spec.captions[:4]):
        size = round(unit * (0.075 if index == 0 else 0.062))
        font = load_font(max(14, size), True, caption, spec.font_path)
        lines = wrap_text(measure, caption, font, max_width - 2 * pad, 2)
        line_h = round(max(14, size) * 1.2)
        text_w = round(max(measure.textlength(line, font=font) for line in lines))
        box = Image.new("RGBA", (text_w + 2 * pad, len(lines) * line_h + pad + pad // 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(box)
        palette = spec.palette or DEFAULT_PALETTE
        draw.rounded_rectangle((0, 0, box.width - 1, box.height - 1), radius=max(10, pad // 2), fill=(*palette.panel, palette.caption_alpha))
        draw.rectangle((pad, box.height - max(3, pad // 4), pad + min(text_w, round(unit * 0.12)), box.height - 2), fill=palette.accent)
        for row, line in enumerate(lines):
            _text(draw, (pad, pad // 2 + row * line_h), line, font, palette.text, palette, max(14, size))
        # captions share the whole ad (a message on screen at all times); the last one stays to the end
        count = len(spec.captions[:4])
        each = max(CAPTION_SECONDS, (duration - CAPTION_FIRST_START) / count) if duration else CAPTION_SECONDS
        start = CAPTION_FIRST_START + index * each
        layers.append(OverlayLayer(
            "caption", _save_layer(box, folder, f"caption-{index}"), (width - box.width) // 2, margin + round(unit * 0.02),
            start, 0.5, dx=(0, round(unit * 0.12), -round(unit * 0.12))[index % 3], dy=round(unit * 0.05) if index % 3 == 0 else 0,
            end=None if index == count - 1 else start + each - 0.3, motion="overshoot",
        ))
    return layers


def render_overlay(width: int, height: int, spec: OverlaySpec, out_path: Path) -> list[str]:
    """Draw every layer, in place, onto one transparent PNG (the static overlay). Returns warnings about anything skipped."""
    folder = out_path.parent / f"{out_path.stem}-layers"
    layers, warnings = render_layers(width, height, spec, folder)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for layer in [layer for layer in layers if layer.kind != "caption"]:  # timed captions only exist in the animated version
        with Image.open(layer.path) as image:
            canvas.alpha_composite(image.convert("RGBA"), (layer.x, layer.y))
    canvas.save(out_path)
    shutil.rmtree(folder, ignore_errors=True)
    return warnings


def _ease(layer: OverlayLayer) -> str:
    """How far the layer still is from its place: 1 before it starts, 0 when settled (ease, overshoot or spring)."""
    s, d = layer.start, layer.duration
    remaining = f"max(0,min(1,1-(t-{s})/{d}))"
    if layer.motion == "spring":  # damped oscillation: arrives fast, bounces past and settles
        return f"if(lt(t,{s}),1,exp(-7*(t-{s}))*cos(16*(t-{s})))"
    if layer.motion == "overshoot":  # cubic ease-out that slightly passes its place before settling
        return f"(pow({remaining},3)-0.12*sin(PI*(1-{remaining}))*{remaining})"
    return f"pow({remaining},2)"


def _attention(layer: OverlayLayer, amplitude: int) -> str:
    """A short, decaying bounce at `attention_at` (0 elsewhere)."""
    if layer.attention_at is None:
        return "0"
    a = layer.attention_at
    return f"if(gte(t,{a}),{amplitude}*abs(sin(9*(t-{a})))*exp(-2.5*(t-{a})),0)"


def animated_overlay_args(src: Path, layers: list[OverlayLayer], duration: float, out: Path) -> list[str]:
    """FFmpeg arguments that fade and slide each layer into place over the video (logo, panel, QR, then the CTA)."""
    args = [ffmpeg_path(), "-y", "-loglevel", "error", "-i", str(src)]
    for layer in layers:
        args += ["-loop", "1", "-framerate", "24", "-i", str(layer.path)]
    graph: list[str] = []
    previous = "0:v"
    for index, layer in enumerate(layers, start=1):
        fade_out = f",fade=t=out:st={layer.end:.3f}:d=0.3:alpha=1" if layer.end is not None else ""
        graph.append(f"[{index}:v]format=rgba,fade=t=in:st={layer.start}:d={layer.duration}:alpha=1{fade_out}[l{index}]")
        x = f"{layer.x}-{layer.dx}*{_ease(layer)}" if layer.dx else str(layer.x)
        y = f"{layer.y}+{layer.dy}*{_ease(layer)}" if layer.dy else str(layer.y)
        if layer.attention_at is not None:
            y = f"{y}-{_attention(layer, max(4, abs(layer.dy) // 2))}"
        graph.append(f"[{previous}][l{index}]overlay=x='{x}':y='{y}':eval=frame:format=auto[b{index}]")
        previous = f"b{index}"
    graph.append(f"[{previous}]format=yuv420p[v]")
    return args + [
        "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "0:a?", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", str(out),
    ]


async def finalize_video(src: Path, dst: Path, spec: OverlaySpec, *, timeout: float = 180.0, animate: bool = True) -> FinalizeResult:
    """Overlay `spec` on `src` and write `dst` (animated in by default). On any problem the raw video is kept, with a warning."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not spec.has_any:
        _copy(src, dst)
        return FinalizeResult(dst, False)
    folder = dst.with_suffix(".layers")
    temp = dst.with_suffix(".tmp.mp4")
    try:
        info = await probe_video(src)
        if spec.palette is None:
            frames = await sample_frames(src, info.duration, folder)
            spec = replace(spec, palette=palette_from_frames(frames, spec.brand_colors))
        layers, warnings = await asyncio.to_thread(render_layers, info.width, info.height, spec, folder, info.duration)
        try:
            if animate and layers and info.duration > 0:
                await run_tool(animated_overlay_args(src, layers, info.duration, temp), timeout=timeout)
            else:
                overlay = folder / "overlay.png"
                await asyncio.to_thread(render_overlay, info.width, info.height, spec, overlay)
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
            shutil.rmtree(folder, ignore_errors=True)
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
