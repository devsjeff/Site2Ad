"""Video types and their shot structures, platform sizes, duration planning and the run folder layout."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

FPS = 30
WORDS_PER_SECOND = 2.0  # measured: the Indian-English voices speak 1.9 to 2.1 words a second (the US voice 2.5); the build speeds a line up by at most 25%
MIN_SHOT_SECONDS = 1.8
STAGES = ("capture", "notes", "brand", "assumptions", "storyboard", "build", "check")

PLATFORM_SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


class StageError(Exception):
    """A stage cannot continue; the message says what to do."""


@dataclass(frozen=True)
class Beat:
    """One shot of a structure: what it is for, how much of the length it gets, which sourced claim kind it needs."""

    id: str
    purpose: str
    weight: float
    needs: str = ""  # claim kind this beat needs: price | proof | quote | stat | availability (empty: any claim)
    visual: str = "any"  # any | screenshot (must show real footage) | graphic


def _b(id: str, purpose: str, weight: float, needs: str = "", visual: str = "any") -> Beat:
    return Beat(id, purpose, weight, needs, visual)


CTA = _b("cta", "Call to action: the one thing to do next, with where to do it", 1.1, visual="graphic")

STRUCTURES: dict[str, tuple[Beat, ...]] = {
    "promo": (
        _b("offer_hook", "Offer hook: the offer in one line", 1.2),
        _b("what_you_get", "What you get: the concrete things included", 1.4),
        _b("proof", "Proof: evidence that it works", 1.2, "proof"),
        _b("price_deadline", "Price or deadline: what it costs or how long the offer lasts", 1.2, "price"),
        CTA,
    ),
    "hook_ad": (
        _b("pain", "Relatable pain: a situation the viewer recognises", 1.1),
        _b("setup", "Setup: make the pain specific", 1.0),
        _b("turn", "Turn (punchline): the twist that reframes the pain", 1.2),
        _b("product", "Product: what it is, as the answer", 1.3),
        _b("proof", "Proof: evidence that it works", 1.1, "proof"),
        _b("price", "Price: what it costs", 1.0, "price"),
        CTA,
    ),
    "pitch": (
        _b("problem", "Problem: what is broken today", 1.2),
        _b("why_now", "Why now: what changed that makes this the moment", 1.0),
        _b("solution", "Solution: what the product is", 1.2),
        _b("how_it_works", "How it works: the mechanism in plain words", 1.3),
        _b("traction", "Traction / proof: evidence with numbers", 1.2, "proof"),
        _b("ask", "Ask: what you want from the viewer", 1.0),
        CTA,
    ),
    "showcase": (
        _b("result_first", "Result first: the finished outcome, shown", 1.5, visual="screenshot"),
        _b("feature_1", "Feature 1: one real feature, shown", 1.3, visual="screenshot"),
        _b("feature_2", "Feature 2: one real feature, shown", 1.3, visual="screenshot"),
        _b("feature_3", "Feature 3: one real feature, shown", 1.3, visual="screenshot"),
        CTA,
    ),
    "explainer": (
        _b("question", "Question: the thing the viewer wonders", 1.0),
        _b("analogy", "Simple analogy: explain it with something familiar", 1.3),
        _b("step_1", "Step 1", 1.1),
        _b("step_2", "Step 2", 1.1),
        _b("step_3", "Step 3", 1.1),
        _b("outcome", "Outcome: what the viewer ends up with", 1.2),
        CTA,
    ),
    "testimonial": (
        _b("customer_problem", "Customer problem: where the customer started", 1.3),
        _b("quote", "Quote: the customer's real words", 1.6, "quote"),
        _b("result_numbers", "Result with numbers: what changed", 1.4, "stat"),
        CTA,
    ),
    "launch": (
        _b("teaser", "Teaser: create curiosity without saying what it is", 1.0),
        _b("reveal", "Reveal: what it is", 1.3),
        _b("key_feature", "Key feature: the one thing that matters most", 1.3, visual="screenshot"),
        _b("availability_price", "Availability / price: when and how much", 1.2, "availability"),
        CTA,
    ),
}
VIDEO_TYPES = tuple(STRUCTURES)

GRAPHIC_TEMPLATES = {
    "title": '{"headline": str, "sub": str}',
    "big_number": '{"from": str, "to": str, "label": str}  (a change from one figure to another, e.g. "20 MIN" to "45 MIN")',
    "steps": '{"steps": [str, ...]}  (2 to 4 short steps)',
    "stats": '{"stats": [{"value": str, "label": str}, ...]}  (1 to 3 figures)',
    "price": '{"price": str, "unit": str, "note": str}',
    "quote": '{"quote": str, "who": str}  (ONLY for a claim of kind "quote" that you cite: the exact words of the customer and the real name or role the notes give; never for any other claim)',
    "compare": '{"left_label": str, "left": str, "right_label": str, "right": str}',
    "cta": '{"headline": str, "button": str, "url": str}',
}
TRANSITIONS = ("cut", "fade", "slide", "zoom")


def min_length(video_type: str) -> int:
    """The shortest length (seconds) in which every shot of the structure still gets time to be read."""
    return int(len(STRUCTURES[video_type]) * 2)


def allocate(length: float, beats: tuple[Beat, ...]) -> list[float]:
    """Seconds for each shot: proportional to the beat weights, in half seconds, never below MIN_SHOT_SECONDS, adding up to `length`."""
    units = round(length * 2)  # half seconds
    floor_units = int(MIN_SHOT_SECONDS * 2 + 0.999)
    if units < floor_units * len(beats):
        raise StageError(f"{length:g} seconds is too short for {len(beats)} shots (each shot needs at least {MIN_SHOT_SECONDS:g} seconds).")
    total_weight = sum(b.weight for b in beats)
    raw = [units * b.weight / total_weight for b in beats]
    counts = [max(floor_units, int(r)) for r in raw]
    while sum(counts) > units:  # give back from the shots that have the most spare time
        index = max(range(len(counts)), key=lambda i: counts[i] - floor_units)
        counts[index] -= 1
    order = sorted(range(len(raw)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    position = 0
    while sum(counts) < units:
        counts[order[position % len(order)]] += 1
        position += 1
    return [c / 2 for c in counts]


def words_limit(seconds: float) -> int:
    """The most words a shot may hold: the build speeds a line up by at most 25%, so this is 25% above the comfortable count."""
    return int(words_allowed(seconds) * 1.25)


def words_allowed(seconds: float) -> int:
    """How many spoken words fit in a shot of this length (the voice starts a moment after the shot does)."""
    return max(3, int((seconds - 0.4) * WORDS_PER_SECOND))


def slug_for(url: str) -> str:
    """A short folder name for a website: 'https://www.backseatnetwork.com/x' -> 'backseatnetwork-com'."""
    host = (urlparse(url if "//" in url else f"//{url}").hostname or "site").removeprefix("www.")
    return re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-") or "site"


def normalize_url(url: str) -> str:
    """Add the scheme people leave out."""
    url = url.strip()
    return url if "://" in url else f"https://{url}"


class Run:
    """A run folder. Each stage's files have fixed names, so stages can be run on their own."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    # --- stage 1
    @property
    def capture_dir(self) -> Path:
        return self._dir("01_capture")

    @property
    def shots_dir(self) -> Path:
        return self._dir("01_capture/screenshots")

    @property
    def assets_dir(self) -> Path:
        return self._dir("01_capture/assets")

    @property
    def page_md(self) -> Path:
        return self.capture_dir / "page.md"

    @property
    def screenshots_md(self) -> Path:
        return self.capture_dir / "screenshots.md"

    @property
    def capture_json(self) -> Path:
        return self.capture_dir / "capture.json"

    # --- stages 2 to 5
    @property
    def product_json(self) -> Path:
        return self.root / "02_product_notes.json"

    @property
    def product_md(self) -> Path:
        return self.root / "02_product_notes.md"

    @property
    def brand_json(self) -> Path:
        return self.root / "03_brand_notes.json"

    @property
    def brand_md(self) -> Path:
        return self.root / "03_brand_notes.md"

    @property
    def assumptions_json(self) -> Path:
        return self.root / "04_assumptions.json"

    @property
    def assumptions_md(self) -> Path:
        return self.root / "04_assumptions.md"

    @property
    def storyboard_json(self) -> Path:
        return self.root / "05_storyboard.json"

    @property
    def storyboard_md(self) -> Path:
        return self.root / "05_storyboard.md"

    # --- stages 6 and 7
    @property
    def build_dir(self) -> Path:
        return self._dir("06_build")

    @property
    def check_dir(self) -> Path:
        return self._dir("07_check")

    @property
    def report_md(self) -> Path:
        return self.check_dir / "report.md"

    @property
    def final_mp4(self) -> Path:
        return self.root / "final.mp4"

    @property
    def request_json(self) -> Path:
        return self.root / "request.json"

    def _dir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --- helpers
    def read(self, path: Path, stage: str) -> Any:
        """Load a saved JSON file, or say which stage has to run first."""
        if not path.is_file():
            raise StageError(f"{path.name} is missing. Run the '{stage}' stage first.")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def write_json(path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def request(self) -> dict:
        """The input of this run: {url, video_type, length, platform, claims}."""
        return self.read(self.request_json, "capture")
