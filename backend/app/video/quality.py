"""Deterministic checks on a finished ad before it is reported as done.

Checks that need no paid service: the file exists and is not empty, it has a video stream with a real size, and its
length is close to what was planned. Brand relevance, text readability, CTA clarity, pacing and visual quality are NOT
judged here; `CreativeEvaluator` is the extension point for such a check (none is configured by default).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from .base import VideoError, probe_media

MIN_BYTES = 1024
DURATION_TOLERANCE_SECONDS = 1.0
DURATION_TOLERANCE_RATIO = 0.10


@dataclass
class QualityReport:
    """What the checks found. `problems` block publishing; `warnings` are shown to the user."""

    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = False


class CreativeEvaluator(Protocol):
    """Optional future check of the creative itself (brand fit, readability, CTA clarity, pacing, visual quality).

    Implementations return plain-language findings; they are added as warnings and never block an ad on their own.
    No evaluator ships with the project, so no paid model is called by default.
    """

    async def evaluate(self, video: Path, brief: object) -> list[str]:
        """Findings about the finished video."""
        ...


async def check_output(path: Path, *, expected_seconds: Optional[float] = None) -> QualityReport:
    """Validate a finished MP4: present, non-empty, a real video stream, and (when known) about the planned length."""
    if not path.is_file():
        return QualityReport(False, ["The finished video file was not created."])
    size = path.stat().st_size
    if size < MIN_BYTES:
        return QualityReport(False, [f"The finished video file is empty ({size} bytes)."])
    try:
        info = await probe_media(path)
    except VideoError:
        return QualityReport(False, ["The finished video has no readable video stream."])
    report = QualityReport(True, duration=info.duration, width=info.width, height=info.height, has_audio=info.has_audio)
    if info.width < 2 or info.height < 2:
        report.problems.append(f"The finished video has no real picture size ({info.width}x{info.height}).")
    if info.duration < 0.5:
        report.problems.append("The finished video is shorter than half a second.")
    if expected_seconds and info.duration >= 0.5:
        tolerance = max(DURATION_TOLERANCE_SECONDS, expected_seconds * DURATION_TOLERANCE_RATIO)
        if abs(info.duration - expected_seconds) > tolerance:
            report.warnings.append(f"The finished video is {info.duration:.1f} seconds long; {expected_seconds:.1f} seconds were planned.")
    report.ok = not report.problems
    return report
