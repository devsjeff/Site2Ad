"""Sound for an ad: a human-sounding voiceover that speaks each on-screen line while it is on screen, over a soft music bed.

The voice comes from Microsoft's neural voices through edge-tts (no API key; the short ad script is sent to that service).
Every line is made separately and placed at the start of its caption, then sped up a little (never more than MAX_TEMPO)
when it is longer than its slot. The music is synthesised by FFmpeg, so it is free to use and ducks under the voice.
Sound is a bonus: when it fails the ad is kept and the user is told.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import catalog
from .base import VideoError, ffmpeg_path, probe_media, probe_seconds, run_tool

logger = logging.getLogger(__name__)

MAX_TEMPO = 1.25  # faster than this stops sounding human
LEAD_IN_SECONDS = 0.12  # the voice starts just after the text appears
TAIL_SECONDS = 0.15
VOICE_TIMEOUT = 45.0
PARALLEL_VOICES = 3


def spoken(text: str) -> str:
    """Text as it should be read: digits of a phone number one by one, no symbols."""
    def digits(match: re.Match) -> str:
        return " ".join(re.sub(r"\D", "", match.group(0)))

    return re.sub(r"\+?\d[\d\s()-]{6,}\d", digits, text).replace("→", "to").strip()


@dataclass
class Cue:
    """One spoken line: when it starts, when it must be finished, what is said, and an optional tail that is dropped if it does not fit."""

    start: float
    end: float
    text: str
    extra: str = ""
    # filled in while making the audio
    path: Optional[Path] = None
    tempo: float = 1.0
    trim: float = 0.0  # > 0: the line is cut (with a short fade) at this many seconds because it cannot fit


def build_cues(
    name: str, captions: list[str], cta: str, offer: str, duration: float, schedule: list[tuple[float, float]],
) -> list[Cue]:
    """One cue per on-screen caption, in step with its slot. The call to action ends the ad; the offer rides on the second line.

    Customer quotes are never read: an AI voice must not pose as a real customer.
    """
    cues: list[Cue] = []
    for index, caption in enumerate(captions[:len(schedule)]):
        if caption.startswith("“") or not caption.strip():
            continue
        slot_end = schedule[index + 1][0] if index + 1 < len(schedule) else duration
        cues.append(Cue(schedule[index][0] + LEAD_IN_SECONDS, max(schedule[index][0] + 0.8, slot_end - TAIL_SECONDS), spoken(caption).rstrip(".!")))
    if not cues:
        return cues
    extras: dict[int, list[str]] = {}
    if offer.strip() and not any(offer.lower() in cue.text.lower() for cue in cues):
        extras.setdefault(min(1, len(cues) - 1), []).append(spoken(offer).rstrip(".!"))
    if not any(name.lower() in cue.text.lower() for cue in cues) and name:
        extras.setdefault(len(cues) - 1, []).append(name)
    if cta.strip() and not any(cta.lower() in cue.text.lower() for cue in cues):
        extras.setdefault(len(cues) - 1, []).append(spoken(cta).rstrip(".!"))
    for index, parts in extras.items():
        cues[index].extra = ". ".join(parts)
    return cues


def voice_script(cues: list[Cue]) -> str:
    """The whole script, for the log and the result page."""
    return " ".join(re.sub(r"([.!?])\.$", r"\1", f"{cue.text + ('. ' + cue.extra if cue.extra else '')}.") for cue in cues)


async def synthesize(text: str, voice_id: str, out: Path, *, rate: str = "+3%", pitch: str = "+0Hz") -> None:
    """Write the voiceover as an MP3. Raises VideoError when it cannot be made."""
    try:
        import edge_tts  # imported here so the rest of the app works without it
    except ImportError as exc:
        raise VideoError("the voice package is not installed") from exc
    voice = catalog.VOICES[voice_id]["voice"]
    try:
        await asyncio.wait_for(edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out)), VOICE_TIMEOUT)
    except Exception as exc:  # the library raises its own network and service errors
        logger.warning("voiceover failed: %s", type(exc).__name__)
        raise VideoError("the voice service could not be reached") from exc
    if not out.is_file() or out.stat().st_size == 0:
        raise VideoError("the voice service returned no audio")


def music_source(music_id: str, seconds: float) -> Optional[str]:
    """An FFmpeg lavfi source for a soft chord pad that alternates between two chords; None for no music."""
    info = catalog.MUSIC.get(music_id)
    if not info or not info.get("chords"):
        return None
    first, second = info["chords"]
    pulse = f"(0.62+0.38*sin(2*PI*{info['pulse']}*t))"
    bar = info["bar"]

    def chord(notes: tuple[float, ...]) -> str:
        return "+".join(f"sin(2*PI*{note}*t)" for note in notes)

    sound = f"0.11*{pulse}*if(lt(mod(t\\,{bar * 2})\\,{bar})\\,{chord(first)}\\,{chord(second)})"
    return f"aevalsrc={sound}:s=44100:c=stereo:d={seconds + 1:.2f}"


def mix_args(src: Path, out: Path, *, duration: float, has_audio: bool, cues: list[Cue], music: Optional[str]) -> list[str]:
    """Video stream copied; every spoken line placed at its start, the original sound lowered, the music ducking under the voice."""
    args = [ffmpeg_path(), "-y", "-loglevel", "error", "-i", str(src)]
    graph: list[str] = []
    beds: list[str] = []
    index = 1
    voiced = [cue for cue in cues if cue.path]
    labels: list[str] = []
    for cue in voiced:
        args += ["-i", str(cue.path)]
        chain = f"[{index}:a]aresample=44100,aformat=channel_layouts=stereo"
        if cue.tempo > 1.001:
            chain += f",atempo={cue.tempo:.3f}"
        if cue.trim > 0:
            chain += f",atrim=0:{cue.trim:.3f},afade=t=out:st={max(0.0, cue.trim - 0.15):.3f}:d=0.15"
        delay = round(cue.start * 1000)
        graph.append(f"{chain},adelay={delay}|{delay}[c{index}]")
        labels.append(f"[c{index}]")
        index += 1
    if voiced:
        mixed = f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest" if len(labels) > 1 else f"{labels[0]}anull"
        graph.append(f"{mixed},acompressor=threshold=0.2:ratio=3,apad,volume=1.5,asplit=2[vo][key]")
    if music:
        args += ["-f", "lavfi", "-i", music]
        chain = f"[{index}:a]lowpass=f=1800,aecho=0.8:0.7:60:0.25,volume=1.4"
        if voiced:
            graph.append(f"{chain}[bed];[bed][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[music]")
        else:
            graph.append(f"{chain}[music]")
        beds.append("[music]")
    elif voiced:
        graph.append("[key]anullsink")
    if has_audio:
        graph.append(f"[0:a]aresample=44100,aformat=channel_layouts=stereo,volume={0.3 if voiced else 0.8}[orig]")
        beds.append("[orig]")
    inputs = (["[vo]"] if voiced else []) + beds
    fade = f"afade=t=in:d=0.3,afade=t=out:st={max(0.0, duration - 0.6):.3f}:d=0.6"
    graph.append(f"{''.join(inputs)}amix=inputs={len(inputs)}:duration=longest:normalize=0,alimiter=limit=0.95,{fade}[a]")
    return args + [
        "-filter_complex", ";".join(graph), "-map", "0:v:0", "-map", "[a]", "-t", f"{duration:.3f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(out),
    ]


@dataclass
class SoundResult:
    """What was added; `warnings` tell the user about anything that was left out."""

    voice_used: bool = False
    music_used: bool = False
    script: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


async def _make_cue(cue: Cue, voice_id: str, folder: Path, number: int, rate: str, pitch: str, gate: asyncio.Semaphore) -> bool:
    """Speak one line, shrinking it (the optional tail first, then a small speed-up) to fit its slot. False when it could not be made."""
    slot = max(0.5, cue.end - cue.start)
    path = folder / f"cue-{number}.mp3"
    async with gate:
        try:
            await synthesize(f"{cue.text}. {cue.extra}" if cue.extra else cue.text, voice_id, path, rate=rate, pitch=pitch)
            length = await probe_seconds(path)
            if cue.extra and length / slot > MAX_TEMPO:  # the tail does not fit: say the caption alone
                await synthesize(cue.text, voice_id, path, rate=rate, pitch=pitch)
                length = await probe_seconds(path)
        except VideoError as exc:
            logger.info("voice cue %d skipped: %s", number, exc)
            return False
    cue.path = path
    cue.tempo = min(MAX_TEMPO, max(1.0, length / slot))
    if length / cue.tempo > slot + 0.05:
        cue.trim = slot  # cut it cleanly instead of talking over the next line
    return True


async def add_sound(
    path: Path, folder: Path, *, voice_id: str, music_id: str, cues: list[Cue], rate: str = "+3%", pitch: str = "+0Hz", timeout: float = 120.0,
) -> SoundResult:
    """Replace `path` with the same video plus the voiceover and music. On failure the silent video stays in place."""
    folder.mkdir(parents=True, exist_ok=True)
    info = await probe_media(path)
    warnings: list[str] = []
    voiced: list[Cue] = []
    if voice_id != "none" and cues:
        gate = asyncio.Semaphore(PARALLEL_VOICES)
        made = await asyncio.gather(*(_make_cue(cue, voice_id, folder, number, rate, pitch, gate) for number, cue in enumerate(cues)))
        voiced = [cue for cue, ok in zip(cues, made) if ok]
        if not voiced:
            warnings.append("The voiceover was left out because the voice service could not be reached.")
        elif len(voiced) < len(cues):
            warnings.append("Some lines of the voiceover could not be made and were left out.")
    music = music_source(music_id, info.duration)
    if not voiced and music is None:
        return SoundResult(warnings=tuple(warnings))
    temp = path.with_suffix(".sound.mp4")
    try:
        await run_tool(mix_args(path, temp, duration=info.duration, has_audio=info.has_audio, cues=voiced, music=music), timeout=timeout)
        temp.replace(path)
    except (VideoError, OSError) as exc:
        logger.warning("sound mix failed: %s", exc)
        return SoundResult(warnings=(*warnings, "The sound could not be added, so the ad is silent."))
    finally:
        temp.unlink(missing_ok=True)
    return SoundResult(voice_used=bool(voiced), music_used=music is not None, script=voice_script(voiced), warnings=tuple(warnings))
