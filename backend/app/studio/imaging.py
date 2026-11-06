"""Picture analysis for the studio: is a screenshot empty, where is its real content, and which part of it should fill a frame.

A page that only shows "try searching to get started" is mostly one flat colour. Such a screenshot makes a poor video, so the
capture stage drops it, and the scenes crop every real screenshot to the content instead of showing it small on empty white.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

ANALYSIS_WIDTH = 360
DIFFERENT = 36  # summed RGB difference from the background colour that counts as "something is drawn here"
EMPTY_BELOW = 0.01  # a picture with less than 1% drawn pixels is empty


def _analysis(path: Path) -> tuple[Image.Image, tuple[int, int, int], list[list[bool]]]:
    """The picture downscaled, its background colour (the most common one) and a mask of the pixels that differ from it."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    width = min(ANALYSIS_WIDTH, image.width)
    small = image.resize((width, max(1, round(image.height * width / image.width))), Image.BILINEAR)
    pixels = list(small.getdata())
    background = Counter((r // 8 * 8, g // 8 * 8, b // 8 * 8) for r, g, b in pixels).most_common(1)[0][0]
    mask = []
    for y in range(small.height):
        row = pixels[y * small.width:(y + 1) * small.width]
        mask.append([abs(r - background[0]) + abs(g - background[1]) + abs(b - background[2]) > DIFFERENT for r, g, b in row])
    return image, background, mask


def drawn_share(path: Path) -> float:
    """The share of the picture that is drawn on (text, images, buttons) rather than flat background."""
    _, _, mask = _analysis(path)
    total = sum(len(row) for row in mask)
    return sum(sum(row) for row in mask) / total if total else 0.0


def is_empty(path: Path) -> bool:
    return drawn_share(path) < EMPTY_BELOW


def content_box(path: Path) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) in pixels of the region that has content; the whole picture when it cannot tell."""
    image, _, mask = _analysis(path)
    height, width = len(mask), len(mask[0]) if mask else 0
    if not width or not height:
        return 0, 0, image.width, image.height
    min_row, min_col = max(1, round(width * 0.012)), max(1, round(height * 0.012))
    rows = [y for y in range(height) if sum(mask[y]) >= min_row]
    cols = [x for x in range(width) if sum(mask[y][x] for y in range(height)) >= min_col]
    if not rows or not cols:
        return 0, 0, image.width, image.height
    pad_x, pad_y = round(width * 0.03), round(height * 0.03)
    left, right = max(0, cols[0] - pad_x), min(width, cols[-1] + 1 + pad_x)
    top, bottom = max(0, rows[0] - pad_y), min(height, rows[-1] + 1 + pad_y)
    scale_x, scale_y = image.width / width, image.height / height
    return round(left * scale_x), round(top * scale_y), round(right * scale_x), round(bottom * scale_y)


def crop_for(path: Path, aspect: float, focus: str = "top", tighten: float = 0.97, whole_width: bool = False) -> dict:
    """The part of a screenshot that fills a frame of this shape (width / height): the content, a little tighter, never empty margins.

    Returns {"x", "y", "w", "h", "iw", "ih"} in pixels of the picture. `focus` picks which end of tall content is shown.
    `whole_width` keeps the content's full width in the crop (for small cards, where a word cut at the edge looks wrong).
    """
    with Image.open(path) as image:
        iw, ih = image.size
    left, top, right, bottom = content_box(path)
    box_w, box_h = right - left, bottom - top
    width = box_w * (1.1 if whole_width else tighten if box_w > iw * 0.7 else 1.0)
    height = width / aspect
    if height > ih:
        height, width = float(ih), ih * aspect
    if width > iw:
        width, height = float(iw), iw / aspect
    center_x = (left + right) / 2
    if box_h > height:  # content taller than the frame: show the start (a heading never loses its top line) or, when asked, the end
        y = bottom - height if focus == "bottom" else top
    else:
        y = (top + bottom) / 2 - height / 2
    x = left if width < box_w else center_x - width / 2  # a crop narrower than the content starts at its left edge (so no word is cut in half)
    x = min(max(0.0, x), iw - width)
    y = min(max(0.0, y), ih - height)
    return {"x": round(x), "y": round(y), "w": round(width), "h": round(height), "iw": iw, "ih": ih}


def card_image(path: Path, aspect: float, out: Path) -> Path:
    """A still of the whole width of a screenshot's content in a frame of this shape: padded with the page's own background when the
    content is wider than the frame is tall, cut at the bottom when it is taller. No word is ever cut at the sides."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    left, top, right, bottom = content_box(path)
    region = image.crop((left, top, right, bottom))
    width, height = region.size
    target = max(1, round(width / aspect))
    if target >= height:
        canvas = Image.new("RGB", (width, target), region.getpixel((0, 0)))
        canvas.paste(region, (0, (target - height) // 2))
    else:
        canvas = region.crop((0, 0, width, target))
    canvas.save(out)
    return out


def save_crop(path: Path, crop: dict, out: Path) -> Path:
    """Write the cropped part of a picture to `out` (a still that can be shown on its own)."""
    with Image.open(path) as image:
        image.convert("RGB").crop((crop["x"], crop["y"], crop["x"] + crop["w"], crop["y"] + crop["h"])).save(out)
    return out
