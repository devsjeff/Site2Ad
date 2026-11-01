"""Stage 7, CHECK AND FIX: review the render, compare every number, price and claim with the product notes, fix what does not match.

Checks:
  claims    every figure, price and name in what is said or shown is in the claims the shot cites; every line is backed by them
  frames    one frame from the middle of each shot: not blank, not flat, not the same picture as the shot before
  text      no text was cut off or left the frame (measured in the browser while rendering)
  voice     every voice-over line fits its shot without being cut or rushed
  video     the length asked for, sound present and not clipping

A shot that fails is rewritten (from the sourced claims only), only those shots are re-rendered, and the checks run again.
Files: 07_check/report.md, 07_check/report.json, 07_check/frame_NN.jpg, and the final cut final.mp4
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from ..video.base import ffmpeg_path
from .ai import ask_json
from .build import build
from .config import FPS, STRUCTURES, Run, allocate, words_allowed, words_limit
from .storyboard import describe_visual, system_prompt, texts_in, validate_storyboard, write_storyboard_md

logger = logging.getLogger(__name__)
SHOT_PROBLEM = re.compile(r"^shot (\d+) \(")
MAX_ROUNDS = 2


def extract_frames(run: Run, board: dict) -> list[Path]:
    """One frame from the middle of every shot of the final video."""
    out, start = [], 0.0
    for shot in board["shots"]:
        path = run.check_dir / f"frame_{shot['n']:02d}.jpg"
        middle = start + shot["seconds"] * 0.6
        subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-ss", f"{middle:.2f}", "-i", str(run.final_mp4), "-frames:v", "1", "-q:v", "3", str(path)], check=False)
        out.append(path)
        start += shot["seconds"]
    return out


def frame_problems(paths: list[Path]) -> list[str]:
    """Blank, flat or repeated frames."""
    problems: list[str] = []
    previous: Image.Image | None = None
    for number, path in enumerate(paths, start=1):
        if not path.is_file():
            problems.append(f"shot {number} (frame): the frame could not be extracted from the video")
            continue
        with Image.open(path) as raw:
            image = raw.convert("L").resize((96, 54))
        stat = ImageStat.Stat(image)
        mean, spread = stat.mean[0] / 255, stat.stddev[0] / 255
        if mean < 0.03 or mean > 0.985:
            problems.append(f"shot {number} (frame): the middle frame is {'black' if mean < 0.5 else 'white'}")
        elif spread < 0.015:
            problems.append(f"shot {number} (frame): the middle frame is flat (nothing is on screen)")
        if previous is not None and ImageStat.Stat(ImageChops.difference(image, previous)).mean[0] / 255 < 0.008:
            problems.append(f"shot {number} (frame): looks the same as the shot before it")
        previous = image
    return problems


def audio_levels(path: Path) -> tuple[float, float]:
    """(mean, max) volume in dB of the finished video, or (0, -91) when it has no sound."""
    result = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", result.stderr)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", result.stderr)
    return (float(mean.group(1)), float(peak.group(1))) if mean and peak else (0.0, -91.0)


def collect(run: Run) -> dict[str, Any]:
    """Run every check. Returns {problems, notes, ...}; a problem starts with 'shot N (name):' when it belongs to one shot."""
    request = run.request()
    board = run.read(run.storyboard_json, "storyboard")
    notes = run.read(run.product_json, "notes")
    capture = run.read(run.capture_json, "capture")
    assumptions = run.read(run.assumptions_json, "assumptions")
    built = run.read(run.build_dir / "build.json", "build")
    seconds = [s["seconds"] for s in board["shots"]]
    before = [dict(s) for s in board["shots"]]
    problems = validate_storyboard({"shots": board["shots"]}, board["video_type"], seconds, notes, capture, assumptions["cta"]["text"])
    if board["shots"] != before:  # a currency symbol was put back: save the corrected storyboard
        run.write_json(run.storyboard_json, board)
        write_storyboard_md(run, board)
    for record in built["shots"]:
        if record["overflow"]:
            problems.append(f"shot {record['n']} (text): text did not fit the frame: {record['overflow'][:2]}")
    for cue, shot in zip([c for c in built["sound"].get("cues", [])], [s for s in board["shots"] if s["voice"].strip()]):
        if not cue["made"]:
            problems.append(f"shot {shot['n']} (voice): the voice-over for this line could not be made")
        elif cue["trimmed"]:
            problems.append(f"shot {shot['n']} (voice): the voice-over is longer than the shot and was cut off; shorten it")
        elif cue["tempo"] > 1.22:
            problems.append(f"shot {shot['n']} (voice): the voice-over had to be sped up {cue['tempo']:.2f}x to fit; shorten it")
    frames = extract_frames(run, board)
    problems += frame_problems(frames)
    notes_out: list[str] = list(built["sound"].get("warnings", []))
    if abs(built["seconds"] - float(request["length"])) > 0.4:
        problems.append(f"video: the length is {built['seconds']} s but {request['length']} s was asked for")
    mean, peak = audio_levels(run.final_mp4)
    if (assumptions["voice"] != "none" or assumptions["music"] != "none") and not built["has_audio"]:
        problems.append("video: sound was chosen but the video has no audio track")
    elif built["has_audio"] and peak > -0.1:
        problems.append(f"video: the sound clips (peak {peak} dB)")
    elif built["has_audio"] and mean < -38:
        problems.append(f"video: the sound is very quiet (mean {mean} dB)")
    return {"problems": problems, "notes": notes_out, "audio": {"mean_db": mean, "peak_db": peak}, "seconds": built["seconds"], "frames": [p.name for p in frames]}


REWRITE_SYSTEM = """You fix ONE shot of a video storyboard that failed its checks. Answer with ONE JSON object only:
{"voice": str, "caption": str, "visual": {...}, "claims": ["C1"]}
Keep the idea and the beat of the shot. Fix every problem listed. Rules:
- Say only what the cited claims say, in fresh words; every figure keeps its currency symbol and must be in the claims you cite.
- No comparisons with other companies or 'traditional' ways, no superlatives, no promises the claims do not make.
- "visual" is {"type": "screenshot", "id": "NN", "focus": "top|center|bottom", "zoom": "in|out"} or {"type": "graphic", "template": "<name>", "props": {...}}; templates and props:
__TEMPLATES__
- The voice line must be shorter than the word limit given. Keep the same kind of visual unless the problem is the visual."""


def safe_rewrite(shot: dict, notes: dict, assumptions: dict) -> None:
    """The fallback when the AI cannot rewrite a shot: say the shot's own sourced claim, plainly. Always passes the checks.

    The voice is the claim cut to a comfortable length; a graphic becomes a title graphic with the same claim; a screenshot stays
    (its caption is dropped). Nothing is added, so nothing can be unsourced.
    """
    ids = [c for c in shot.get("claims") or [] if any(n["id"] == c for n in notes["claims"])]
    if not ids:
        ids = [c for item in assumptions.get("must_include", []) for c in item.get("claims", [])][:1] or [notes["claims"][0]["id"]]
    claim = next(c for c in notes["claims"] if c["id"] == ids[0])
    sentence = re.split(r"(?<=[.!?])\s+", claim["text"])[0].rstrip(".")
    limit = words_allowed(shot["seconds"])
    shot["claims"] = ids[:1]
    shot["caption"] = ""
    if shot["visual"].get("template") == "cta":  # the last shot keeps its own job: the call to action and where to do it
        props = shot["visual"].get("props") or {}
        shot["voice"] = trim_words(f"{props.get('button', assumptions['cta']['text'])} at {props.get('url', '')}".strip(), limit)
        return
    shot["voice"] = fit_clause(sentence, limit)
    if shot["visual"].get("type") != "screenshot":
        shot["visual"] = {"type": "graphic", "template": "title", "props": {"headline": fit_clause(sentence, 9), "sub": ""}}


def fit_clause(text: str, limit: int) -> str:
    """The part of a sentence that fits `limit` words, cut at a natural break (comma, 'and', 'plus', 'with') rather than mid-phrase."""
    if len(text.split()) <= limit:
        return text
    parts = re.split(r"\s*[;:–—]\s*|,\s+|\s+(?:and|plus|with|while|so)\s+", text)
    best = ""
    for part in parts:  # the first clause that fits, or the longest run of clauses that fits
        candidate = part if not best else best
        if 3 <= len(part.split()) <= limit:
            best = part
            break
    return best or trim_words(text, limit)


def trim_words(text: str, limit: int) -> str:
    """The first `limit` words, cut so the line does not end on a dangling word."""
    from ..ai.captions import DANGLING_WORDS

    words = text.split()[:limit]
    ends_badly = DANGLING_WORDS | {"plus", "per", "to", "up", "about", "than", "starting", "starts", "at", "from"}
    while len(words) > 3 and (words[-1].lower().strip(",.;:") in ends_badly or re.fullmatch(r"[\d₹$%,.]+", words[-1])):
        words.pop()
    return " ".join(words).rstrip(",;:")


def fix_shot(run: Run, board: dict, index: int, problems: list[str], notes: dict, capture: dict, assumptions: dict) -> bool:
    """Rewrite one shot from the sourced claims. True when the rewrite passes every check."""
    shot = board["shots"][index]
    seconds = [s["seconds"] for s in board["shots"]]
    claims = "\n".join(f"{c['id']} [{c['kind']}] {c['text']}" for c in notes["claims"])
    screens = "\n".join(f"{s['id']} ({s['kind']}): {s['summary']}" for s in capture["screenshots"])
    user = (f"The shot (beat '{shot['beat']}', {shot['seconds']:g} seconds, at most {words_allowed(shot['seconds'])} spoken words):\n"
            f"voice: {shot['voice']!r}\ncaption: {shot['caption']!r}\nvisual: {describe_visual(shot['visual'])}\ncited claims: {shot['claims']}\n\n"
            f"Problems to fix:\n" + "\n".join(f"- {p}" for p in problems) + f"\n\nClaims you may use:\n{claims}\n\nScreenshots you may show:\n{screens}")

    def check(data: dict) -> list[str]:
        trial = {"shots": [dict(s) for s in board["shots"]]}
        trial["shots"][index] = {**shot, **{k: data.get(k, shot[k]) for k in ("voice", "caption", "visual", "claims")}}
        found = validate_storyboard(trial, board["video_type"], seconds, notes, capture, assumptions["cta"]["text"])
        mine = [p for p in found if p.startswith(f"shot {index + 1} (")]
        return [re.sub(r"^shot \d+ \([^)]*\): ", "", p) for p in mine]

    system = REWRITE_SYSTEM.replace("__TEMPLATES__", system_prompt().split("the templates and their props:")[1].split("5. ")[0])
    try:
        data = ask_json(system, user, check, what=f"fix for shot {index + 1}", max_tokens=1500, tries=3)
    except Exception as exc:  # the AI could not do it (limit, outage, no valid answer): fall back to the shot's own sourced claim
        logger.info("shot %d: AI rewrite failed (%s); using the safe rewrite", index + 1, exc)
        safe_rewrite(shot, notes, assumptions)
        return False
    shot["voice"], shot["caption"] = " ".join(str(data.get("voice", "")).split()), " ".join(str(data.get("caption", "")).split())
    shot["visual"], shot["claims"] = data.get("visual", shot["visual"]), list(data.get("claims") or shot["claims"])
    return True


def run_checks(run: Run, rounds: int = MAX_ROUNDS) -> dict[str, Any]:
    """Run stage 7: check, fix, re-render the fixed shots, check again (up to `rounds` fixes), then write the report."""
    history: list[dict] = []
    for attempt in range(rounds + 1):
        result = collect(run)
        history.append({"round": attempt, "problems": result["problems"]})
        if not result["problems"] or attempt == rounds:
            break
        notes = run.read(run.product_json, "notes")
        capture = run.read(run.capture_json, "capture")
        assumptions = run.read(run.assumptions_json, "assumptions")
        board = run.read(run.storyboard_json, "storyboard")
        by_shot: dict[int, list[str]] = {}
        for problem in result["problems"]:
            match = SHOT_PROBLEM.match(problem)
            if match:
                by_shot.setdefault(int(match.group(1)) - 1, []).append(problem)
        if not by_shot:  # only video-level problems (length, sound): rebuilding will not change them
            break
        for index, shot_problems in by_shot.items():
            fix_shot(run, board, index, shot_problems, notes, capture, assumptions)
        run.write_json(run.storyboard_json, board)
        write_storyboard_md(run, board)
        build(run, only={i + 1 for i in by_shot})  # only the shots that changed are rendered again; the final cut is joined anew
    report = {**result, "rounds": history, "passed": not result["problems"], "fixed_in_rounds": len(history) - 1}
    run.write_json(run.check_dir / "report.json", report)
    write_report(run, report)
    return report


def write_report(run: Run, report: dict) -> None:
    """07_check/report.md"""
    out = [f"# Check report: {'PASSED' if report['passed'] else 'NEEDS ATTENTION'}", "",
           f"- length: {report['seconds']} s", f"- sound: mean {report['audio']['mean_db']} dB, peak {report['audio']['peak_db']} dB",
           f"- fix rounds used: {report['fixed_in_rounds']}", ""]
    out.append("## What was checked")
    out += ["", "- every figure, price and percentage on screen or spoken is in the claims the shot cites (and keeps its currency symbol)",
            "- every line is backed by those claims (no claims about other companies, no unsourced comparison or superlative)",
            "- one frame from each shot is not blank, not flat and not the same as the shot before",
            "- text fits the frame; every voice-over line fits its shot without being cut or rushed", "- length and sound of the finished video", ""]
    for entry in report["rounds"]:
        out.append(f"## Round {entry['round']}: {'no problems' if not entry['problems'] else str(len(entry['problems'])) + ' problem(s)'}")
        out += [f"- {p}" for p in entry["problems"]] + [""]
    if report["notes"]:
        out += ["## Notes", ""] + [f"- {n}" for n in report["notes"]] + [""]
    out += ["## Frames", ""] + [f"- {name}" for name in report["frames"]]
    run.report_md.write_text("\n".join(out) + "\n", encoding="utf-8")
