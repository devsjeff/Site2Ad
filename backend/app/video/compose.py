"""FFmpeg composition: original images, uploaded videos and AI clips -> ONE uniform MP4. No AI service is called here.

Every segment is first rendered to the same size, frame rate, pixel format and audio layout, then the segments are
joined with FFmpeg's concat *filter* (re-encoded), which avoids the time-base and codec mismatches that break the
concat demuxer. Segments dip to black where they meet, so the boundaries between original website images and generated
footage stay visible. A short clip can be looped to fill the requested length. Text, logo and QR code are added
afterwards by finalize.py on the complete composition.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .base import VideoError, ffmpeg_path, probe_media, run_tool

logger = logging.getLogger(__name__)

FPS = 24
AUDIO_RATE = 44100
FADE_SECONDS = 0.35
MAX_ZOOM = 1.15
# zoom speed per output frame for each style (gentle by default)
ZOOM_RATE = {"bold_pop": 0.0018, "nightlife_neon": 0.0014, "minimal_modern": 0.0006, "corporate_clean": 0.0007}
DEFAULT_ZOOM_RATE = 0.0009


@dataclass
class Segment:
    """One input to the composition. Images play for `seconds`; videos play in full, cut at `seconds` when it is > 0.

    `loop_to` > 0 repeats a video until it lasts that many seconds (used for short AI clips).
    """

    kind: str  # schemas.SegmentKind
    path: Path
    is_image: bool
    seconds: float = 0.0
    source: str = ""
    framed: bool = False  # draw a thin light border so an original image is clearly not generated footage
    loop_to: float = 0.0


@dataclass
class ComposedSegment:
    """A segment as it ended up in the video."""

    kind: str
    source: str
    seconds: float


@dataclass
class ComposeResult:
    """The composed MP4 and what is in it."""

    path: Path
    duration: float
    has_audio: bool
    segments: list[ComposedSegment] = field(default_factory=list)
    width: int = 0
    height: int = 0


def _fades(seconds: float, fade_in: bool = True, fade_out: bool = True) -> str:
    """Fade in from black and/or out to black (skipped for very short pieces)."""
    if seconds < 4 * FADE_SECONDS:
        return ""
    out = f",fade=t=in:st=0:d={FADE_SECONDS}" if fade_in else ""
    return out + (f",fade=t=out:st={seconds - FADE_SECONDS:.3f}:d={FADE_SECONDS}" if fade_out else "")


def image_filter(index: int, seconds: float, size: tuple[int, int], style: str, framed: bool, fades: str = "") -> str:
    """Slow zoom in (even segments) or out (odd segments) over a still image that already has the frame's size."""
    width, height = size
    frames = max(1, round(seconds * FPS))
    rate = ZOOM_RATE.get(style, DEFAULT_ZOOM_RATE)
    zoom = f"min(1+{rate}*on,{MAX_ZOOM})" if index % 2 == 0 else f"max({MAX_ZOOM}-{rate}*on,1)"
    border = ""
    if framed:
        thickness = max(4, round(min(width, height) * 0.012))
        border = f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t={thickness}"
    # drawn at 2x first so the zoom stays smooth (zoompan on small inputs jitters)
    return (
        f"scale={width * 2}:{height * 2},zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={width}x{height}:fps={FPS},setsar=1{border},format=yuv420p{fades}"
    )


def video_filter(size: tuple[int, int], fades: str = "") -> str:
    """Fit a video into the frame without cropping or stretching (black bars when the shape differs)."""
    width, height = size
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={FPS},format=yuv420p{fades}"
    )


def _audio_filter(seconds: float, fade_in: bool, fade_out: bool) -> str:
    """Uniform audio layout, with matching fades so the joins do not click."""
    base = f"aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
    if seconds < 4 * FADE_SECONDS:
        return base
    if fade_in:
        base += f",afade=t=in:st=0:d={FADE_SECONDS}"
    if fade_out:
        base += f",afade=t=out:st={seconds - FADE_SECONDS:.3f}:d={FADE_SECONDS}"
    return base


VIDEO_CODEC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]
AUDIO_CODEC = ["-c:a", "aac", "-b:a", "128k", "-ar", str(AUDIO_RATE), "-ac", "2"]
SILENCE = ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]


async def render_segment(
    segment: Segment, index: int, out: Path, *, size: tuple[int, int], style: str, with_audio: bool, keep_source_audio: bool,
    first: bool = True, last: bool = True,
) -> ComposedSegment:
    """Render one segment to a uniform MP4 (same size, fps, pixel format and audio layout as every other segment).

    Segments dip to black where they meet another segment; the very start and end of the ad are not faded, so the
    first frame (the player's preview) shows the real picture.
    """
    ffmpeg = ffmpeg_path()
    if segment.is_image:
        seconds = max(1.0, segment.seconds)
        args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(segment.path)]
        if with_audio:
            args += SILENCE
        fades = _fades(seconds, fade_in=not first, fade_out=not last)
        args += ["-vf", image_filter(index, seconds, size, style, segment.framed, fades), "-frames:v", str(round(seconds * FPS))]
        args += ["-map", "0:v:0"] + (["-map", "1:a:0", *AUDIO_CODEC] if with_audio else ["-an"])
        args += ["-t", f"{seconds:.3f}", *VIDEO_CODEC, str(out)]
    else:
        info = await probe_media(segment.path)
        if info.duration <= 0:
            raise VideoError("A video has no length and cannot be used.")
        looping = segment.loop_to > info.duration + 0.05
        if looping:
            seconds = segment.loop_to
        else:
            seconds = min(info.duration, segment.seconds) if segment.seconds > 0 else info.duration
        use_source_audio = with_audio and keep_source_audio and info.has_audio
        args = [ffmpeg, "-y", "-loglevel", "error"] + (["-stream_loop", "-1"] if looping else []) + ["-i", str(segment.path)]
        if with_audio and not use_source_audio:
            args += SILENCE
        fades = _fades(seconds, fade_in=not first, fade_out=not last)
        args += ["-t", f"{seconds:.3f}", "-vf", video_filter(size, fades), "-map", "0:v:0"]
        if use_source_audio:
            args += ["-map", "0:a:0", "-af", _audio_filter(seconds, not first, not last), *AUDIO_CODEC]
        elif with_audio:
            args += ["-map", "1:a:0", *AUDIO_CODEC]
        else:
            args += ["-an"]
        args += [*VIDEO_CODEC, str(out)]
    await run_tool(args, timeout=max(90.0, seconds * 10))
    if not out.is_file() or out.stat().st_size == 0:
        raise VideoError("A part of the video could not be created.")
    return ComposedSegment(segment.kind, segment.source, round(seconds, 2))


async def compose(
    segments: list[Segment], out: Path, *, size: tuple[int, int], style: str, keep_audio: bool, work_dir: Path,
) -> ComposeResult:
    """Render every segment, then join them in order into `out`. Raises VideoError (temporary files are always removed)."""
    if not segments:
        raise VideoError("There is nothing to put in the video.")
    ffmpeg = ffmpeg_path()
    work_dir.mkdir(parents=True, exist_ok=True)
    parts_dir = work_dir / "segments"
    parts_dir.mkdir(parents=True, exist_ok=True)
    try:
        with_audio = False
        if keep_audio:
            for segment in segments:
                if not segment.is_image and (await probe_media(segment.path)).has_audio:
                    with_audio = True
                    break
        parts: list[Path] = []
        composed: list[ComposedSegment] = []
        for index, segment in enumerate(segments):
            part = parts_dir / f"part-{index:02d}.mp4"
            composed.append(await render_segment(
                segment, index, part, size=size, style=style, with_audio=with_audio, keep_source_audio=keep_audio,
                first=index == 0, last=index == len(segments) - 1,
            ))
            parts.append(part)
        out.parent.mkdir(parents=True, exist_ok=True)
        if len(parts) == 1:
            shutil.move(str(parts[0]), out)
        else:
            args = [ffmpeg, "-y", "-loglevel", "error"]
            for part in parts:
                args += ["-i", str(part)]
            labels = "".join(f"[{i}:v:0]" + (f"[{i}:a:0]" if with_audio else "") for i in range(len(parts)))
            graph = f"{labels}concat=n={len(parts)}:v=1:a={1 if with_audio else 0}[v]" + ("[a]" if with_audio else "")
            args += ["-filter_complex", graph, "-map", "[v]"]
            args += ["-map", "[a]", *AUDIO_CODEC] if with_audio else ["-an"]
            args += [*VIDEO_CODEC, "-movflags", "+faststart", str(out)]
            total = sum(c.seconds for c in composed)
            await run_tool(args, timeout=max(120.0, total * 8))
        info = await probe_media(out)
        return ComposeResult(out, info.duration, info.has_audio, composed, info.width, info.height)
    finally:
        shutil.rmtree(parts_dir, ignore_errors=True)
