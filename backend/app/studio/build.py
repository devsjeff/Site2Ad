"""Stage 6, BUILD: render the motion-graphic scenes frame by frame, join the shots, add the voice and the music.

Voice and music come from the assumptions (the voice reads each shot's line exactly while its shot is on screen). The scenes are
HTML/CSS in the brand colours and fonts with the real screenshots as footage; frames are rendered by a headless browser and
FFmpeg makes the video.

Files: 06_build/scenes/*.html, 06_build/shots/*.mp4, 06_build/cut.mp4, 06_build/build.json, final.mp4
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..video.base import ffmpeg_path, probe_media
from ..video.voice import Cue, add_sound
from .capture import launch_browser
from .config import FPS, PLATFORM_SIZES, Run, StageError
from .figures import speakable
from .scenes import scene_html, theme_from
from .storyboard import site_address

logger = logging.getLogger(__name__)

OVERLAP = {"cut": 0.04, "fade": 0.4, "slide": 0.4, "zoom": 0.45}  # seconds the next shot is blended in while this one ends
XFADE = {"cut": "fade", "fade": "fade", "slide": "slideleft", "zoom": "zoomin"}
SEEK_JS = "ms => document.getAnimations().forEach(a => { a.pause(); a.currentTime = ms; })"
FONTS_JS = "Promise.race([document.fonts.ready.then(() => true), new Promise(r => setTimeout(() => r(false), 7000))])"


def _run(args: list[str], what: str) -> None:
    """Run FFmpeg; a failure says what was being made."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise StageError(f"FFmpeg could not make {what}: {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'unknown error'}")


def render_shots(run: Run, board: dict, theme: dict, size: tuple[int, int], site: str, capture: dict, only: set[int] | None) -> list[dict]:
    """Render every frame of every shot (or only the shots in `only`). Returns per-shot facts: frame count and any text that did not fit."""
    from playwright.sync_api import sync_playwright

    scenes = run.build_dir / "scenes"
    scenes.mkdir(exist_ok=True)
    files = {s["id"]: run.shots_dir / s["file"] for s in capture["screenshots"]}
    info: list[dict] = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            page = browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
            for shot in board["shots"]:
                n = shot["n"]
                overlap = OVERLAP[shot["transition"]] if n < len(board["shots"]) else 0.0
                frames = round((shot["seconds"] + overlap) * FPS)
                folder = run.build_dir / "frames" / f"shot_{n:02d}"
                record = {"n": n, "frames": frames, "overflow": []}
                info.append(record)
                if only is not None and n not in only:
                    continue
                image_url = files[shot["visual"]["id"]].resolve().as_uri() if shot["visual"].get("type") == "screenshot" else ""
                path = scenes / f"shot_{n:02d}.html"
                path.write_text(scene_html(shot, theme, size, site, image_url), encoding="utf-8")
                page.goto(path.resolve().as_uri(), wait_until="load")
                page.evaluate(FONTS_JS)
                page.evaluate(SEEK_JS, int((shot["seconds"] + 1) * 1000))  # the finished state: that is where text must fit
                page.evaluate("window.__fit()")
                record["overflow"] = page.evaluate("window.__overflow")
                shutil.rmtree(folder, ignore_errors=True)
                folder.mkdir(parents=True)
                for index in range(frames):
                    page.evaluate(SEEK_JS, int(index / FPS * 1000))
                    page.screenshot(path=str(folder / f"{index:05d}.jpg"), type="jpeg", quality=92)
                logger.info("shot %d rendered: %d frames%s", n, frames, f", text did not fit: {record['overflow']}" if record["overflow"] else "")
        finally:
            browser.close()
    return info


def encode_shots(run: Run, board: dict, size: tuple[int, int], only: set[int] | None) -> list[Path]:
    """One silent MP4 per shot from its frames."""
    out_dir = run.build_dir / "shots"
    out_dir.mkdir(exist_ok=True)
    paths = []
    for shot in board["shots"]:
        n = shot["n"]
        path = out_dir / f"shot_{n:02d}.mp4"
        paths.append(path)
        if only is not None and n not in only:
            continue
        _run([ffmpeg_path(), "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(run.build_dir / "frames" / f"shot_{n:02d}" / "%05d.jpg"),
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), str(path)], f"shot {n}")
    return paths


def join_shots(board: dict, paths: list[Path], out: Path) -> None:
    """Join the shots with the transition the storyboard chose between them. The total length is exactly the sum of the shot lengths."""
    shots = board["shots"]
    if len(paths) == 1:
        shutil.copy(paths[0], out)
        return
    graph = [f"[{i}:v]fps={FPS},settb=AVTB,format=yuv420p[p{i}]" for i in range(len(paths))]
    previous, elapsed = "p0", 0.0
    for index in range(1, len(paths)):
        elapsed += shots[index - 1]["seconds"]  # the next shot starts blending in at the end of the previous shot's own time
        overlap = OVERLAP[shots[index - 1]["transition"]]
        graph.append(f"[{previous}][p{index}]xfade=transition={XFADE[shots[index - 1]['transition']]}:duration={overlap:.3f}:offset={elapsed:.3f}[x{index}]")
        previous = f"x{index}"
    args = [ffmpeg_path(), "-y", "-loglevel", "error"]
    for path in paths:
        args += ["-i", str(path)]
    args += ["-filter_complex", ";".join(graph), "-map", f"[{previous}]", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-movflags", "+faststart", str(out)]
    _run(args, "the joined video")


def make_cues(board: dict) -> list[Cue]:
    """One voice cue per shot, placed where the shot starts (read as people say it: '₹4,000' becomes '4,000 rupees')."""
    cues: list[Cue] = []
    start = 0.0
    for shot in board["shots"]:
        if shot["voice"].strip():
            cues.append(Cue(start + 0.18, start + shot["seconds"] - 0.08, speakable(shot["voice"]).rstrip(".")))
        start += shot["seconds"]
    return cues


def build(run: Run, only: set[int] | None = None) -> dict[str, Any]:
    """Run stage 6. `only` re-renders just those shots (the others keep their frames) and then re-joins everything."""
    request = run.request()
    board = run.read(run.storyboard_json, "storyboard")
    brand = run.read(run.brand_json, "brand")
    assumptions = run.read(run.assumptions_json, "assumptions")
    capture = run.read(run.capture_json, "capture")
    size = PLATFORM_SIZES[request["platform"]]
    site = site_address(request["url"])
    theme = theme_from(brand)
    info = render_shots(run, board, theme, size, site, capture, only)
    paths = encode_shots(run, board, size, only)
    cut = run.build_dir / "cut.mp4"
    join_shots(board, paths, cut)
    shutil.copy(cut, run.final_mp4)

    cues = make_cues(board)
    sound = {"voice": assumptions["voice"], "music": assumptions["music"], "warnings": []}
    if assumptions["voice"] != "none" or assumptions["music"] != "none":
        folder = run.build_dir / "sound"
        result = asyncio.run(add_sound(run.final_mp4, folder, voice_id=assumptions["voice"], music_id=assumptions["music"], cues=cues, rate="+3%"))
        shutil.rmtree(folder, ignore_errors=True)
        sound["warnings"] = list(result.warnings)
        sound["script"] = result.script
        sound["cues"] = [{"start": round(c.start, 2), "end": round(c.end, 2), "tempo": round(c.tempo, 2), "trimmed": c.trim > 0, "text": c.text, "made": c.path is not None} for c in cues]
    media = asyncio.run(probe_media(run.final_mp4))
    record = {"size": size, "fps": FPS, "seconds": round(media.duration, 2), "has_audio": media.has_audio, "shots": info, "sound": sound}
    run.write_json(run.build_dir / "build.json", record)
    return record
