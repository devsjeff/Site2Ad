"""Sound effects for videos: whooshes, pops, dings, risers and chimes that FFmpeg synthesises itself.

Nothing is downloaded and no recording is used, so every effect is original and free of copyright, works offline (and inside Docker),
and sounds the same on every machine. `library()` makes the WAV files; `Effect` says when one plays; `shot_effects()` knows which
effect belongs to which animation of a Studio scene (so a price that stamps in is heard stamping in).
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .base import ffmpeg_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Effect:
    """A sound effect at a time (seconds from the start of the video) and a loudness (1.0 = as made)."""

    time: float
    name: str
    gain: float = 1.0


def _ping(frequency: float, start: float, decay: float, volume: float = 1.0) -> str:
    """A decaying sine note that begins at `start` seconds (an aevalsrc term)."""
    return f"gt(t,{start})*{volume}*sin(2*PI*{frequency}*(t-{start}))*exp(-(t-{start})*{decay})"


def _pop_expression() -> str:
    return "0.9*sin(2*PI*(240+950*exp(-t*38))*t)*exp(-t*26)"


# name -> (lavfi source, extra filters). Each is a short stereo WAV.
RECIPES: dict[str, tuple[str, str]] = {
    "pop": (f"aevalsrc='{_pop_expression()}':s=44100:d=0.24", "volume=0.9"),
    "tick": ("anoisesrc=d=0.06:c=white:r=44100:a=0.7", "highpass=f=2600,afade=t=out:st=0.0:d=0.06,volume=0.8"),
    "swish": ("anoisesrc=d=0.5:c=pink:r=44100:a=0.8", "highpass=f=700,lowpass=f=6500,afade=t=in:d=0.18,afade=t=out:st=0.18:d=0.32,volume=0.7"),
    "whoosh": ("anoisesrc=d=0.95:c=pink:r=44100:a=0.95",
               "highpass=f=200,lowpass=f=4200,tremolo=f=3:d=0.15,afade=t=in:d=0.4,afade=t=out:st=0.4:d=0.55,aecho=0.7:0.5:70:0.25,volume=0.85"),
    "impact": ("aevalsrc='0.95*sin(2*PI*(52+120*exp(-t*16))*t)*exp(-t*6.5)+0.35*(random(0)*2-1)*exp(-t*70)':s=44100:d=0.8", "lowpass=f=900,volume=1.0"),
    "ding": (f"aevalsrc='0.5*sin(2*PI*1568*t)*exp(-t*4.2)+0.3*sin(2*PI*2349*t)*exp(-t*5.2)+0.18*sin(2*PI*3136*t)*exp(-t*7)':s=44100:d=1.2", "volume=0.9"),
    "chime": (f"aevalsrc='0.42*sin(2*PI*1047*t)*exp(-t*5.5)+{_ping(1319, 0.09, 5.5, 0.42)}+{_ping(1568, 0.18, 4.5, 0.42)}+{_ping(2093, 0.27, 3.6, 0.34)}':s=44100:d=1.4",
              "aecho=0.6:0.4:90:0.2,volume=0.9"),
    "sparkle": (f"aevalsrc='{_ping(2093, 0, 9, 0.3)}+{_ping(2637, 0.05, 9, 0.28)}+{_ping(3136, 0.1, 9, 0.26)}+{_ping(3951, 0.16, 9, 0.24)}+"
                f"{_ping(2794, 0.22, 9, 0.22)}+{_ping(3520, 0.29, 9, 0.2)}':s=44100:d=0.9", "volume=0.9"),
    "riser": ("aevalsrc='0.4*sin(2*PI*(160*t+(1800/3)*t*t*t))*pow(t/1.0,1.5)':s=44100:d=1.0", "volume=0.9"),
    "riser_short": ("aevalsrc='0.4*sin(2*PI*(240*t+(3000/3)*t*t*t))*pow(t/0.36,1.4)':s=44100:d=0.36", "afade=t=out:st=0.3:d=0.06,volume=0.9"),
}


def library(folder: Path) -> dict[str, Path]:
    """Make every effect as a WAV file in `folder` (already made ones are reused). An effect that cannot be made is simply left out."""
    folder.mkdir(parents=True, exist_ok=True)
    made: dict[str, Path] = {}
    for name, (source, filters) in RECIPES.items():
        path = folder / f"{name}.wav"
        if path.is_file() and path.stat().st_size > 0:
            made[name] = path
            continue
        args = [ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", source, "-af", f"{filters},aformat=channel_layouts=stereo", "-ar", "44100", str(path)]
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0 and path.is_file() and path.stat().st_size > 0:
            _normalise(path)
            made[name] = path
        else:
            logger.warning("sound effect %s could not be made: %s", name, result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown error")
    return made


PEAK_DB = -3.0  # every effect is brought to the same peak, so the gains in shot_effects() mean the same for all of them


def _normalise(path: Path) -> None:
    """Raise (or lower) an effect so its loudest point is PEAK_DB; a quiet whoosh and a loud impact then mix as written."""
    probe = subprocess.run([ffmpeg_path(), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    match = re.search(r"max_volume: (-?[\d.]+) dB", probe.stderr)
    if not match:
        return
    gain = max(-12.0, min(24.0, PEAK_DB - float(match.group(1))))
    if abs(gain) < 0.5:
        return
    temp = path.with_suffix(".norm.wav")
    result = subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-i", str(path), "-af", f"volume={gain:.1f}dB,alimiter=limit=0.8", str(temp)], capture_output=True, text=True)
    if result.returncode == 0 and temp.is_file():
        temp.replace(path)
    else:
        temp.unlink(missing_ok=True)


# How each Studio scene animates (see scenes.py): the effects follow those moments.
def shot_effects(shot: dict) -> list[tuple[float, str, float]]:
    """(seconds after the shot starts, effect, gain) for the animations of one shot."""
    visual = shot.get("visual") or {}
    if visual.get("type") == "screenshot":
        out = [(0.02, "swish", 0.5)]
        if shot.get("caption"):
            out.append((0.5, "pop", 0.6))
        return out
    template = visual.get("template")
    props = visual.get("props") or {}
    if template == "title":
        out = [(0.1, "pop", 0.7)]
        if props.get("sub"):
            out.append((0.9, "pop", 0.35))
        return out
    if template == "big_number":
        return [(0.2, "pop", 0.5), (1.0, "tick", 0.7), (1.22, "impact", 0.55), (1.3, "ding", 0.5)]
    if template == "steps":
        return [(0.15 + 0.4 * i, "pop", 0.65) for i in range(min(4, len(props.get("steps") or [])))]
    if template == "stats":
        return [(0.15 + 0.35 * i, "pop", 0.65) for i in range(min(3, len(props.get("stats") or [])))]
    if template == "price":
        return [(0.0, "riser_short", 0.55), (0.3, "impact", 0.6), (0.34, "ding", 0.6)]
    if template == "quote":
        return [(0.0, "pop", 0.6), (0.3, "swish", 0.35)]
    if template == "compare":
        return [(0.1, "swish", 0.5), (0.55, "swish", 0.5), (0.72, "pop", 0.6)]
    if template == "cta":
        return [(0.05, "swish", 0.4), (0.8, "pop", 0.75), (0.82, "chime", 0.6), (0.9, "sparkle", 0.45)]
    return [(0.1, "pop", 0.6)]


def transition_effect(kind: str) -> tuple[str, float, float]:
    """(effect, gain, seconds before the new shot starts) for the transition into a shot."""
    return {
        "slide": ("whoosh", 0.75, 0.08),
        "zoom": ("impact", 0.5, 0.0),
        "fade": ("swish", 0.4, 0.05),
        "cut": ("tick", 0.8, 0.0),
    }.get(kind, ("swish", 0.4, 0.05))


def effects_for_board(shots: list[dict]) -> list[Effect]:
    """Every sound effect of a storyboard, with times from the start of the video."""
    effects: list[Effect] = []
    start = 0.0
    for index, shot in enumerate(shots):
        if index == 0:
            effects.append(Effect(0.0, "impact", 0.5))
        else:
            name, gain, lead = transition_effect(shots[index - 1].get("transition", "fade"))
            effects.append(Effect(max(0.0, start - lead), name, gain))
        for offset, name, gain in shot_effects(shot):
            if offset < shot["seconds"] - 0.2:
                effects.append(Effect(start + offset, name, gain))
        start += shot["seconds"]
    return sorted(effects, key=lambda e: e.time)
