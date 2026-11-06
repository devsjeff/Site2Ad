"""Command line for the studio pipeline.

    python -m app.studio run --url https://example.com --type promo --length 20 --platform 16:9
    python -m app.studio capture|notes|brand|assumptions|storyboard|build|check --run <folder>

`run` goes through every stage in order. Each stage reads the files the stage before saved in the run folder, so a stage can
be run again on its own, or after you edit a file by hand (for example 04_assumptions.json).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from .config import PLATFORM_SIZES, STAGES, VIDEO_TYPES, Run, StageError, normalize_url, slug_for

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "studio"


def say(message: str) -> None:
    """Print a line, even if the console cannot show every character."""
    print(message.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"), flush=True)


def stage_capture(run: Run, args: argparse.Namespace) -> None:
    from .pipeline import run_capture, validate_request

    request = {"url": normalize_url(args.url or run.request()["url"]), "video_type": args.type, "length": args.length, "platform": args.platform,
               "claims": args.claim or [], "fix_rounds": args.fix_rounds}
    validate_request(request)
    run.write_json(run.request_json, request)
    say(f"  {run_capture(run, policy())} -> {run.capture_dir}")
    say(f"  see {run.screenshots_md.name}: one line per screenshot")


def policy():
    """The network rules of the scanner (backend/.env can lift them for local testing)."""
    from ..config import Settings
    from ..scraper.safety import SafetyPolicy

    return SafetyPolicy.from_settings(Settings.from_env())


def stage_notes(run: Run, args: argparse.Namespace) -> None:
    from .pipeline import run_notes

    say(f"  {run_notes(run)} -> {run.product_md.name}")


def stage_brand(run: Run, args: argparse.Namespace) -> None:
    from .pipeline import run_brand

    say(f"  {run_brand(run)} -> {run.brand_md.name}")


def stage_assumptions(run: Run, args: argparse.Namespace) -> None:
    from .pipeline import run_assumptions

    run_assumptions(run)
    say("")
    say(run.assumptions_md.read_text(encoding="utf-8"))
    say(f"  -> edit {run.assumptions_json.name} to correct anything, then run the next stage")


def stage_storyboard(run: Run, args: argparse.Namespace) -> None:
    from .pipeline import run_storyboard

    say(f"  {run_storyboard(run)} -> {run.storyboard_md.name}")


def stage_build(run: Run, args: argparse.Namespace) -> None:
    from .pipeline import run_build

    say(f"  built {run_build(run)} -> {run.final_mp4}")


def stage_check(run: Run, args: argparse.Namespace) -> None:
    from .check import run_checks

    report = run_checks(run, rounds=args.fix_rounds)
    say(f"  {'PASSED' if report['passed'] else 'NEEDS ATTENTION'}: {len(report['problems'])} problem(s) left after {report['fixed_in_rounds']} fix round(s) -> {run.report_md}")
    for problem in report["problems"]:
        say(f"    - {problem}")


RUNNERS = {"capture": stage_capture, "notes": stage_notes, "brand": stage_brand, "assumptions": stage_assumptions,
           "storyboard": stage_storyboard, "build": stage_build, "check": stage_check}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.studio", description="A staged pipeline that makes a typed video from a website.")
    p.add_argument("stage", choices=("run", *STAGES), help="'run' does every stage; or one stage on its own")
    p.add_argument("--url", help="the website (needed for 'run' and 'capture')")
    p.add_argument("--type", default="promo", choices=VIDEO_TYPES, help="video type (default promo)")
    p.add_argument("--length", type=float, default=20, help="length in seconds (default 20)")
    p.add_argument("--platform", default="16:9", choices=tuple(PLATFORM_SIZES), help="16:9, 9:16 or 1:1 (default 16:9)")
    p.add_argument("--run", type=Path, help="the run folder (default: data/studio/<site>-<type>)")
    p.add_argument("--claim", action="append", help="a sourced fact of your own to add to the notes (repeatable), e.g. a customer quote or a price")
    p.add_argument("--review", action="store_true", help="with 'run': stop after the assumptions so you can correct them")
    p.add_argument("--from", dest="start", choices=STAGES, help="with 'run': start at this stage (the earlier stages' files are reused)")
    p.add_argument("--fix-rounds", type=int, default=2, help="how many times the check stage may fix and re-render (default 2)")
    p.add_argument("--model", help="the AI model to try first (default: fast free OpenRouter models, then the model in backend/.env)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    if args.model:
        os.environ["STUDIO_MODEL"] = args.model
    run_dir = args.run
    if run_dir is None:
        if not args.url:
            say("Give --run <folder> (an existing run) or --url <website>.")
            return 2
        run_dir = DEFAULT_ROOT / f"{slug_for(args.url)}-{args.type}"
    run = Run(Path(run_dir))
    stages = list(STAGES) if args.stage == "run" else [args.stage]
    if args.stage == "run" and args.start:
        stages = stages[STAGES.index(args.start):]
    if "capture" in stages and not args.url and not run.request_json.is_file():
        say("The capture stage needs --url.")
        return 2
    say(f"Run folder: {run.root}")
    for number, stage in enumerate(stages, start=1):
        started = time.time()
        say(f"[{STAGES.index(stage) + 1}/7] {stage}")
        try:
            RUNNERS[stage](run, args)
        except StageError as exc:
            say(f"  STOPPED: {exc}")
            return 1
        say(f"  ({time.time() - started:.0f} s)")
        if stage == "assumptions" and args.stage == "run" and args.review:
            say("Stopped for your review. Edit 04_assumptions.json if you like, then run:")
            say(f"  python -m app.studio run --run \"{run.root}\" --from storyboard")
            return 0
    if run.final_mp4.is_file() and "build" in stages:
        say(f"\nDone: {run.final_mp4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
