"""The seven stages as plain functions: `RUNNERS[name](run, policy)` does one stage and returns one line saying what it did.

The command line (cli.py) and the website's jobs (jobs.py) both call these, so they cannot drift apart. Every stage reads the files of
the stage before it from the run folder, and the run's input from request.json.
"""

from __future__ import annotations

from typing import Callable

from .. import catalog
from ..scraper.safety import DEFAULT_POLICY, SafetyPolicy
from .config import STAGES, STRUCTURES, VIDEO_TYPES, Run, StageError, min_length

LABELS = {
    "capture": "Reading your website", "notes": "Writing product notes", "brand": "Finding your brand", "assumptions": "Choosing the direction",
    "storyboard": "Planning the shots", "build": "Making the video", "check": "Checking every number",
}
# How much of the whole job each stage is (for a progress bar); they add up to 100.
WEIGHTS = {"capture": 10, "notes": 20, "brand": 5, "assumptions": 10, "storyboard": 15, "build": 25, "check": 15}


def validate_request(request: dict) -> None:
    """The input of a run, checked once (a clear message instead of a failure three stages later)."""
    if request.get("video_type") not in VIDEO_TYPES:
        raise StageError(f"video type must be one of {', '.join(VIDEO_TYPES)}")
    language = request.get("language", "en")
    if language not in catalog.LANGUAGES:
        raise StageError(f"language must be one of {', '.join(catalog.LANGUAGES)}")
    voice = request.get("voice", "auto")
    if voice != "auto" and (voice not in catalog.VOICES or language not in catalog.VOICES[voice]["languages"] or voice == "none"):
        raise StageError(f"the voice '{voice}' does not speak {catalog.LANGUAGES[language]['label']}; choose one of: {', '.join(catalog.voices_for(language))}")
    needed = min_length(request["video_type"])
    if float(request.get("length", 0)) < needed:
        raise StageError(f"a {request['video_type']} video has {len(STRUCTURES[request['video_type']])} shots and needs at least {needed} seconds")


def run_capture(run: Run, policy: SafetyPolicy = DEFAULT_POLICY) -> str:
    from .capture import capture

    request = run.request()
    validate_request(request)
    record = capture(run, request["url"], policy)
    return f"{len(record['blocks'])} text blocks and {len(record['screenshots'])} screenshots"


def run_notes(run: Run, policy: SafetyPolicy = DEFAULT_POLICY) -> str:
    from .notes import build_notes

    notes = build_notes(run, run.request().get("claims", []))
    return f"{len(notes['claims'])} claims with sources ({len(notes['rejected'])} left out)"


def run_brand(run: Run, policy: SafetyPolicy = DEFAULT_POLICY) -> str:
    from .brand import build_brand

    brand = build_brand(run)
    return f"primary {brand['colors']['primary']}, fonts {brand['fonts']['heading']} / {brand['fonts']['body']}"


def run_assumptions(run: Run, policy: SafetyPolicy = DEFAULT_POLICY) -> str:
    from .assumptions import build_assumptions

    build_assumptions(run, run.request()["video_type"])
    return "audience, key message, tone, voice, music, must-include and must-avoid chosen"


def run_storyboard(run: Run, policy: SafetyPolicy = DEFAULT_POLICY) -> str:
    from .storyboard import build_storyboard

    board = build_storyboard(run)
    return f"{len(board['shots'])} shots, {board['length']:g} seconds"


def run_build(run: Run, policy: SafetyPolicy = DEFAULT_POLICY) -> str:
    from .build import build

    record = build(run)
    return f"{record['seconds']} seconds at {record['size'][0]}x{record['size'][1]}"


def run_check(run: Run, policy: SafetyPolicy = DEFAULT_POLICY) -> str:
    from .check import run_checks

    report = run_checks(run, rounds=int(run.request().get("fix_rounds", 2)))
    return ("passed" if report["passed"] else f"{len(report['problems'])} problem(s) left") + f" after {report['fixed_in_rounds']} fix round(s)"


RUNNERS: dict[str, Callable[..., str]] = {
    "capture": run_capture, "notes": run_notes, "brand": run_brand, "assumptions": run_assumptions,
    "storyboard": run_storyboard, "build": run_build, "check": run_check,
}
assert tuple(RUNNERS) == STAGES
