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

from .. import catalog
from ..video import voice as voice_engine
from ..video.base import ffmpeg_path, probe_media
from ..video.sfx import effects_for_board
from ..video.voice import Cue, add_sound
from .capture import launch_browser
from .config import FPS, PLATFORM_SIZES, Run, StageError
from .figures import speakable
from .imaging import card_image, crop_for
from .scenes import art_aspect, scene_html, screenshot_aspect, theme_from
from .storyboard import site_address
from .translate import ensure_translations

logger = logging.getLogger(__name__)

OVERLAP = {"cut": 0.04, "fade": 0.4, "slide": 0.4, "zoom": 0.45}  # seconds the next shot is blended in while this one ends
# Each kind of transition cycles through several FFmpeg blends, so a video does not repeat one effect after another.
XFADE_VARIANTS = {
    "cut": ["fade"],
    "fade": ["fade", "dissolve", "fade"],
    "slide": ["slideleft", "smoothleft", "slideup", "wipeleft", "slideright", "smoothup"],
    "zoom": ["zoomin", "circleopen", "radial"],
}


def xfade_name(kind: str, index: int) -> str:
    """The FFmpeg blend for the transition after shot number `index` (0-based)."""
    variants = XFADE_VARIANTS.get(kind, ["fade"])
    return variants[index % len(variants)]
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
    assets = capture.get("assets") or {}
    logo = run.capture_dir / assets["logo"]["file"] if assets.get("logo") and (run.capture_dir / assets["logo"]["file"]).exists() else None
    art = [run.capture_dir / a["file"] for a in assets.get("images", []) if (run.capture_dir / a["file"]).exists()]
    aspect = screenshot_aspect(size)
    if not art:  # no pictures of their own: a close crop of a real screenshot beside the headline
        art_dir = run.build_dir / "art"
        art_dir.mkdir(exist_ok=True)
        for number, shot_file in enumerate(files.values(), start=1):
            if shot_file.exists():
                art.append(card_image(shot_file, art_aspect(size), art_dir / f"peek_{number:02d}.png"))
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
                is_screenshot = shot["visual"].get("type") == "screenshot"
                image_file = files[shot["visual"]["id"]] if is_screenshot else None
                image_url = image_file.resolve().as_uri() if image_file else ""
                crop = crop_for(image_file, aspect, shot["visual"].get("focus", "top")) if image_file else None
                art_url = art[(n - 1) % len(art)].resolve().as_uri() if art else ""
                path = scenes / f"shot_{n:02d}.html"
                path.write_text(scene_html(shot, theme, size, site, image_url, crop, logo.resolve().as_uri() if logo else "", art_url), encoding="utf-8")
                page.goto(path.resolve().as_uri(), wait_until="load")
                page.evaluate(FONTS_JS)
                page.evaluate(SEEK_JS, int((shot["seconds"] + 1) * 1000))  # the finished state: that is where text must fit
                page.evaluate("window.__fit()")
                record["overflow"] = page.evaluate("window.__overflow")
                shutil.rmtree(folder, ignore_errors=True)
                folder.mkdir(parents=True)
                for index in range(frames):
                    page.evaluate(SEEK_JS, int(index / FPS * 1000))
                    page.screenshot(path=str(folder / f"{index:05d}.jpg"), type="jpeg", quality=94)
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
        shutil.rmtree(run.build_dir / "frames" / f"shot_{n:02d}", ignore_errors=True)  # the shot is encoded; its frames are only disk
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
        graph.append(f"[{previous}][p{index}]xfade=transition={xfade_name(shots[index - 1]['transition'], index - 1)}:duration={overlap:.3f}:offset={elapsed:.3f}[x{index}]")
        previous = f"x{index}"
    args = [ffmpeg_path(), "-y", "-loglevel", "error"]
    for path in paths:
        args += ["-i", str(path)]
    args += ["-filter_complex", ";".join(graph), "-map", f"[{previous}]", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-movflags", "+faststart", str(out)]
    _run(args, "the joined video")


def make_cues(board: dict, language: str = "en") -> list[Cue]:
    """One voice cue per shot, placed where the shot starts. In English a figure is read as people say it ('₹4,000' becomes '4,000 rupees');
    in another language the translated line is used (it already spells the currency out)."""
    cues: list[Cue] = []
    start = 0.0
    for shot in board["shots"]:
        if shot["voice"].strip():
            text = shot.get("voice_local") if language != "en" and shot.get("voice_local") else speakable(shot["voice"])
            cues.append(Cue(start + 0.18, start + shot["seconds"] - 0.08, text.rstrip(".")))
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

    voice_engine.ensure_configured()
    voice_id, language, warnings = assumptions["voice"], assumptions.get("language", "en"), []
    if voice_id != "none" and language != "en":
        note = ensure_translations(board, language)  # one request for the lines that are new or changed; the English storyboard stays the checked text
        run.write_json(run.storyboard_json, board)
        if note:  # the writer could not translate: speak English (with a voice that speaks it) and say so
            warnings.append(note)
            language = "en"
            if "en" not in catalog.VOICES[voice_id]["languages"]:
                voice_id = catalog.fallback_voice(voice_id, "en")
    cues = make_cues(board, language) if voice_id != "none" else []  # no voice: no cues (so the check does not report lines that were never meant to be spoken)
    effects = effects_for_board(board["shots"]) if assumptions.get("sound_effects", True) else []
    sound = {"voice": voice_id, "music": assumptions["music"], "language": language, "warnings": warnings, "effects": len(effects)}
    if voice_id != "none" or assumptions["music"] != "none" or effects:
        folder = run.build_dir / "sound"
        result = asyncio.run(add_sound(run.final_mp4, folder, voice_id=voice_id, music_id=assumptions["music"], cues=cues, rate="+3%",
                                       language=language, effects=effects))
        shutil.rmtree(folder, ignore_errors=True)
        sound["warnings"] = warnings + list(result.warnings)
        sound["engine"] = result.engine
        sound["effects_used"] = result.effects_used
        sound["script"] = result.script
        sound["cues"] = [{"start": round(c.start, 2), "end": round(c.end, 2), "tempo": round(c.tempo, 2), "trimmed": c.trim > 0, "text": c.text, "made": c.path is not None} for c in cues]
    media = asyncio.run(probe_media(run.final_mp4))
    record = {"size": size, "fps": FPS, "seconds": round(media.duration, 2), "has_audio": media.has_audio, "shots": info, "sound": sound}
    run.write_json(run.build_dir / "build.json", record)
    return record
