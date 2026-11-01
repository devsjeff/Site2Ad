"""Hero image and logo preparation: download safely, validate, fix orientation, crop to the ad's aspect ratio."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from .. import catalog
from ..scraper.fetch import Deadline, Fetcher

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 60_000_000  # Pillow raises DecompressionBombError above 2x this; we refuse above 1x below
MAX_SOURCE_PIXELS = 60_000_000
HARD_MIN_SIDE = 200  # below this a still image makes a poor video, so it is refused


class ImageProblem(Exception):
    """An image could not be used. The message is safe to show to the user."""


@dataclass
class PreparedImage:
    """An image on disk that is ready to be used."""

    path: Path
    width: int
    height: int
    source_width: int
    source_height: int
    warnings: list[str] = field(default_factory=list)


async def download_image(fetcher: Fetcher, url: str, *, max_bytes: int, seconds: float = 15.0) -> bytes:
    """Download an image through the SSRF-safe fetcher. Raises ImageProblem with a plain-language reason."""
    result = await fetcher.get_binary(url, Deadline(seconds), max_bytes=max_bytes)
    if result.ok and result.body:
        return result.body
    reasons = {
        "unsafe": "That image address is not allowed.",
        "timeout": "The image took too long to download.",
        "too_large": "The image file is too large.",
        "wrong_type": "That address is not an image.",
        "http_error": f"The image could not be downloaded (status {result.status_code}).",
    }
    raise ImageProblem(reasons.get(result.error_code) or result.error or "The image could not be downloaded.")


def _open(raw: bytes) -> Image.Image:
    """Open image bytes with Pillow, refusing SVG, huge or unreadable files."""
    head = raw[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in raw[:2048].lower()):
        raise ImageProblem("SVG images cannot be used for video. Pick a JPG, PNG or WebP photo.")
    try:
        image = Image.open(io.BytesIO(raw))
        width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageProblem("That file is not a readable image (use JPG, PNG or WebP).") from None
    if width * height > MAX_SOURCE_PIXELS:
        raise ImageProblem("The image is too large in pixels.")
    return image


def _to_rgb(image: Image.Image) -> Image.Image:
    """Apply EXIF rotation and flatten transparency on white."""
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        return background
    return image.convert("RGB")


def cover_crop(image: Image.Image, aspect_ratio: str) -> Image.Image:
    """Crop (never stretch) an image to the target aspect ratio around its centre."""
    aw, ah = catalog.parse_aspect(aspect_ratio)
    target = aw / ah
    width, height = image.size
    if width / height > target:  # too wide: trim the sides
        new_width = round(height * target)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = round(width / target)  # too tall: trim top and bottom, keeping slightly more of the top
    top = max(0, round((height - new_height) * 0.4))
    return image.crop((0, top, width, top + new_height))


def prepare_hero(raw: bytes, out_path: Path, aspect_ratio: str, *, min_side: int, max_long_side: int = 1920) -> PreparedImage:
    """Validate bytes as a hero image, crop to the aspect ratio and save a clean JPEG. Raises ImageProblem."""
    image = _open(raw)
    source_w, source_h = image.size
    if min(source_w, source_h) < HARD_MIN_SIDE:
        raise ImageProblem(f"The image is too small ({source_w}x{source_h}). Use a photo at least {min_side}px on its short side.")
    try:
        image = _to_rgb(image)
    except (OSError, ValueError):
        raise ImageProblem("The image file is damaged.") from None
    image = cover_crop(image, aspect_ratio)
    warnings: list[str] = []
    if min(image.size) < min_side:
        warnings.append(f"The hero image is small ({source_w}x{source_h}); the video may look soft. A larger photo works better.")
    long_side = max(image.size)
    if long_side > max_long_side:
        scale = max_long_side / long_side
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=92, optimize=True)
    return PreparedImage(out_path, image.width, image.height, source_w, source_h, warnings)


def prepare_frame(raw: bytes, out_path: Path, aspect_ratio: str, *, size: tuple[int, int], min_side: int) -> PreparedImage:
    """Fit an original image into a video frame without changing what it shows.

    When the image already has (nearly) the frame's shape it is cropped to fill the frame; otherwise the whole image is
    kept and centred on a blurred, darkened copy of itself, so text and products near the edges are never cut off.
    """
    image = _open(raw)
    source_w, source_h = image.size
    if min(source_w, source_h) < HARD_MIN_SIDE:
        raise ImageProblem(f"The image is too small ({source_w}x{source_h}).")
    try:
        image = _to_rgb(image)
    except (OSError, ValueError):
        raise ImageProblem("The image file is damaged.") from None
    width, height = size
    aw, ah = catalog.parse_aspect(aspect_ratio)
    target, actual = aw / ah, image.width / image.height
    warnings: list[str] = []
    if min(source_w, source_h) < min_side:
        warnings.append(f"An image is small ({source_w}x{source_h}) and may look soft in the video.")
    if abs(actual - target) / target <= 0.2:
        frame = cover_crop(image, aspect_ratio).resize((width, height), Image.Resampling.LANCZOS)
    else:
        background = cover_crop(image, aspect_ratio).resize((max(2, width // 8), max(2, height // 8)), Image.Resampling.BILINEAR)
        background = background.filter(ImageFilter.GaussianBlur(3)).resize((width, height), Image.Resampling.BILINEAR)
        frame = ImageEnhance.Brightness(background).enhance(0.55)
        fitted = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
        frame.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(out_path, "JPEG", quality=92, optimize=True)
    return PreparedImage(out_path, frame.width, frame.height, source_w, source_h, warnings)


def frame_quality(path: Path) -> float:
    """How good a prepared frame looks as a video picture: real detail and colour score high; gradients, plain cards and
    washed-out pictures score low (a smooth banner has strong brightness steps but almost no edges)."""
    with Image.open(path) as image:
        small = ImageOps.exif_transpose(image).convert("RGB").resize((192, 108))
    gray = small.convert("L")
    edges = gray.filter(ImageFilter.GaussianBlur(1)).filter(ImageFilter.FIND_EDGES)
    density = sum(1 for value in edges.getdata() if value > 18) / (192 * 108)  # share of the picture that has real edges
    contrast = ImageStat.Stat(gray).stddev[0]
    brightness = ImageStat.Stat(gray).mean[0]
    r, g, b = small.split()
    colour = ImageStat.Stat(ImageChops.difference(r, g)).mean[0] + ImageStat.Stat(ImageChops.difference(g, b)).mean[0]
    score = min(density * 100, 25) * 1.6 + min(contrast, 60) * 0.3 + min(colour, 40) * 0.5
    if density < 0.012:
        score -= 40  # a gradient, a plain card or a blank banner
    if contrast < 14:
        score -= 15
    if brightness < 35 or brightness > 225:
        score -= 15
    return score


def _picture_hash(path: Path) -> int:
    """A 64-bit average hash: two near-identical pictures differ in only a few bits."""
    with Image.open(path) as image:
        tiny = ImageOps.exif_transpose(image).convert("L").resize((8, 8), Image.Resampling.BILINEAR)
    pixels = list(tiny.getdata())
    average = sum(pixels) / len(pixels)
    return sum(1 << index for index, value in enumerate(pixels) if value >= average)


def rank_frames(frames: list[tuple], keep: int, source_sides: Optional[dict] = None) -> list[tuple]:
    """The best `keep` pictures, best first: near-duplicates dropped, flat or washed-out pictures last, the rest in page order.

    Each item is a tuple whose LAST element is the picture's file path (any leading fields are kept as they are).
    The strongest picture opens the ad (it is the hook), then the others follow in the order the website shows them.
    """
    scored = []
    for position, item in enumerate(frames):
        try:
            side = (source_sides or {}).get(item[-1], 0)
            small = max(0.0, (800 - side) / 800 * 40) if side else 0.0  # a small original looks soft and noisy when enlarged
            scored.append((frame_quality(item[-1]) - small, position, item, _picture_hash(item[-1])))
        except (OSError, ValueError):
            scored.append((-100.0, position, item, position))
    unique: list[tuple] = []
    for entry in sorted(scored, key=lambda s: -s[0]):
        if all(bin(entry[3] ^ other[3]).count("1") > 5 for other in unique):
            unique.append(entry)
    chosen = unique[:keep]
    for entry in sorted(scored, key=lambda s: -s[0]):  # too few distinct pictures: allow repeats rather than a short ad
        if len(chosen) >= min(keep, len(scored)):
            break
        if entry not in chosen:
            chosen.append(entry)
    chosen.sort(key=lambda s: s[1])
    best = max(chosen, key=lambda s: s[0])
    return [best[2]] + [entry[2] for entry in chosen if entry is not best]


def prepare_logo(raw: bytes, out_path: Path, max_side: int = 512) -> PreparedImage:
    """Validate bytes as a logo and save a transparent PNG no larger than max_side. Raises ImageProblem."""
    image = _open(raw)
    source_w, source_h = image.size
    if min(source_w, source_h) < 16:
        raise ImageProblem("The logo is too small to use.")
    try:
        image = ImageOps.exif_transpose(image).convert("RGBA")
    except (OSError, ValueError):
        raise ImageProblem("The logo file is damaged.") from None
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return PreparedImage(out_path, image.width, image.height, source_w, source_h)


def sniff_extension(raw: bytes) -> Optional[str]:
    """File extension for the image format in `raw` (jpg, png, webp, gif), or None if it is not a supported image."""
    try:
        fmt = (Image.open(io.BytesIO(raw)).format or "").lower()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    return {"jpeg": "jpg", "png": "png", "webp": "webp", "gif": "gif"}.get(fmt)


def prepare_photo(raw: bytes, out_path: Path, max_side: int = 2048) -> PreparedImage:
    """Validate an uploaded photo and re-encode it as a clean JPEG (this also strips EXIF/GPS and any hidden payload)."""
    image = _open(raw)
    source_w, source_h = image.size
    if min(source_w, source_h) < HARD_MIN_SIDE:
        raise ImageProblem(f"The photo is too small ({source_w}x{source_h}). Use one at least 400px on its short side.")
    try:
        image = _to_rgb(image)
    except (OSError, ValueError):
        raise ImageProblem("The photo file is damaged.") from None
    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=90, optimize=True)
    return PreparedImage(out_path, image.width, image.height, source_w, source_h)
