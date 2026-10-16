"""FFmpeg composition: original images, uploaded videos and AI clips -> ONE uniform MP4. No AI service is called here.

Every segment is first rendered to the same size, frame rate, pixel format and audio layout, then the segments are
joined with FFmpeg's concat *filter* (re-encoded), which avoids the time-base and codec mismatches that break the
concat demuxer. Segments dip to black where they meet, so the boundaries between original website images and generated
footage stay visible. A short clip can be looped to fill the requested length. Text, logo and QR code are added
afterwards by finalize.py on the complete composition.
"""

from __future__ import annotations

import logging
import math
import shutil
from dataclasses import dataclass, field, replace
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


# Camera moves over a still image: (name, zoom, x, y) for zoompan. {r} = zoom speed, {f} = frames, {m} = max zoom.
IMAGE_MOTIONS = (
    ("zoom_in", "min(1+{r}*on,{m})", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("pan_right", "1.12", "(iw-iw/zoom)*on/{f}", "ih/2-(ih/zoom/2)"),
    ("zoom_out", "max({m}-{r}*on,1)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("tilt_up", "1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{f})"),
    ("pan_left", "1.12", "(iw-iw/zoom)*(1-on/{f})", "ih/2-(ih/zoom/2)"),
    ("diagonal", "min(1+{r}*on,{m})", "(iw-iw/zoom)*on/{f}", "(ih-ih/zoom)*on/{f}"),
    ("tilt_down", "1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*on/{f}"),
    ("zoom_in_left", "min(1+{r}*on,{m})", "(iw-iw/zoom)*0.15", "ih/2-(ih/zoom/2)"),
)
# Transitions between segments (FFmpeg xfade), used in turn so the ad does not cut the same way every time.
TRANSITIONS = ("fade", "slideleft", "circleopen", "smoothleft", "wipeup", "dissolve", "slideup", "radial")
TRANSITION_SECONDS = 0.5
# A light, consistent cinematic look on still images: a touch more contrast and colour, and a soft vignette.
IMAGE_GRADE = "eq=contrast=1.05:saturation=1.12,vignette=angle=PI/5"


def image_filter(index: int, seconds: float, size: tuple[int, int], style: str, framed: bool, fades: str = "") -> str:
    """A camera move over a still image (zoom in/out, pans, tilts, diagonal drift: a different one per segment)."""
    width, height = size
    frames = max(1, round(seconds * FPS))
    rate = ZOOM_RATE.get(style, DEFAULT_ZOOM_RATE)
    _, zoom, x, y = (part.format(r=rate, f=frames, m=MAX_ZOOM) for part in IMAGE_MOTIONS[index % len(IMAGE_MOTIONS)])
    border = ""
    if framed:
        thickness = max(4, round(min(width, height) * 0.012))
        border = f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t={thickness}"
    # drawn at 2x first so the zoom stays smooth (zoompan on small inputs jitters)
    return (
        f"scale={width * 2}:{height * 2},zoompan=z='{zoom}':x='{x}':y='{y}'"
        f":d={frames}:s={width}x{height}:fps={FPS},setsar=1{border},{IMAGE_GRADE},format=yuv420p{fades}"
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


LOOP_CROSSFADE_SECONDS = 0.6
# How each repeat of a short clip is reframed, so a loop reads as new shots: (zoom, x, y) for zoompan; {f} = frames per repeat.
LOOP_VARIANTS = (
    ("1", "0", "0"),  # the clip as generated
    ("1+0.10*on/{f}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),  # slow push-in to the centre
    ("1.12-0.10*on/{f}", "(iw-iw/zoom)*0.3", "ih/2-(ih/zoom/2)"),  # pull-out, slightly left
    ("1.08", "(iw-iw/zoom)*on/{f}", "ih/2-(ih/zoom/2)"),  # punched in, panning left to right
)


def loop_plan(clip_seconds: float, total_seconds: float) -> tuple[int, float]:
    """(repeats, crossfade) so that repeats of the clip, overlapped by the crossfade, last at least `total_seconds`."""
    crossfade = min(LOOP_CROSSFADE_SECONDS, clip_seconds / 3)
    repeats = max(1, math.ceil((total_seconds - crossfade) / max(0.1, clip_seconds - crossfade)))
    return repeats, crossfade


def loop_filter(clip_seconds: float, total_seconds: float, size: tuple[int, int], fades: str) -> tuple[int, str]:
    """(inputs needed, filter graph) that plays the clip `repeats` times, each reframed differently, joined by crossfades."""
    width, height = size
    repeats, crossfade = loop_plan(clip_seconds, total_seconds)
    frames = max(1, round(clip_seconds * FPS))
    parts = []
    for index in range(repeats):
        zoom, x, y = (value.format(f=frames) for value in LOOP_VARIANTS[index % len(LOOP_VARIANTS)])
        parts.append(
            f"[{index}:v:0]{video_filter(size)},zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={FPS},"
            f"setsar=1,format=yuv420p,settb=AVTB[v{index}]"
        )
    previous = "v0"
    for index in range(1, repeats):
        offset = index * (clip_seconds - crossfade)
        parts.append(f"[{previous}][v{index}]xfade=transition=fade:duration={crossfade:.3f}:offset={offset:.3f}[x{index}]")
        previous = f"x{index}"
    parts.append(f"[{previous}]trim=duration={total_seconds:.3f},setpts=PTS-STARTPTS{fades}[vout]")
    return repeats, ";".join(parts)


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
        fades = _fades(seconds, fade_in=not first, fade_out=not last)
        if looping:  # every repeat reframed differently and crossfaded, so the loop reads as new shots
            repeats, graph = loop_filter(info.duration, seconds, size, fades)
            args = [ffmpeg, "-y", "-loglevel", "error"]
            for _ in range(repeats):
                args += ["-i", str(segment.path)]
            if use_source_audio:
                args += ["-stream_loop", "-1", "-i", str(segment.path)]
            elif with_audio:
                args += SILENCE
            args += ["-filter_complex", graph, "-map", "[vout]", "-t", f"{seconds:.3f}"]
            if use_source_audio:
                args += ["-map", f"{repeats}:a:0", "-af", _audio_filter(seconds, not first, not last), *AUDIO_CODEC]
            elif with_audio:
                args += ["-map", f"{repeats}:a:0", *AUDIO_CODEC]
            else:
                args += ["-an"]
            args += [*VIDEO_CODEC, str(out)]
        else:
            args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(segment.path)]
            if with_audio and not use_source_audio:
                args += SILENCE
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


def transition_graph(durations: list[float], with_audio: bool) -> str:
    """Join parts with a different xfade transition at each cut (and audio crossfades), as one filter graph."""
    graph = [f"[{i}:v:0]fps={FPS},settb=AVTB,format=yuv420p[p{i}]" for i in range(len(durations))]
    previous, elapsed = "p0", durations[0]
    for index in range(1, len(durations)):
        overlap = min(TRANSITION_SECONDS, durations[index - 1] / 2, durations[index] / 2)
        offset = elapsed - overlap
        kind = TRANSITIONS[(index - 1) % len(TRANSITIONS)]
        graph.append(f"[{previous}][p{index}]xfade=transition={kind}:duration={overlap:.3f}:offset={offset:.3f}[x{index}]")
        previous, elapsed = f"x{index}", offset + durations[index]
    graph.append(f"[{previous}]format=yuv420p[v]")
    if with_audio:
        audio = "0:a:0"
        for index in range(1, len(durations)):
            overlap = min(TRANSITION_SECONDS, durations[index - 1] / 2, durations[index] / 2)
            graph.append(f"[{audio}][{index}:a:0]acrossfade=d={overlap:.3f}[ax{index}]")
            audio = f"ax{index}"
        graph.append(f"[{audio}]anull[a]")
    return ";".join(graph)


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
        joined = len(segments) > 1
        for index, segment in enumerate(segments):
            part = parts_dir / f"part-{index:02d}.mp4"
            planned = segment
            if joined and index < len(segments) - 1:  # the next transition overlaps this part: make it that much longer
                if segment.is_image:
                    planned = replace(segment, seconds=max(1.0, segment.seconds) + TRANSITION_SECONDS)
                elif segment.loop_to:
                    planned = replace(segment, loop_to=segment.loop_to + TRANSITION_SECONDS)
            rendered = await render_segment(
                planned, index, part, size=size, style=style, with_audio=with_audio, keep_source_audio=keep_audio,
                first=True, last=True,  # transitions come from xfade below, not from fades inside each part
            )
            if planned is not segment:
                rendered.seconds = round(rendered.seconds - TRANSITION_SECONDS, 2)
            composed.append(rendered)
            parts.append(part)
        out.parent.mkdir(parents=True, exist_ok=True)
        if not joined:
            shutil.move(str(parts[0]), out)
        else:
            durations = [(await probe_media(part)).duration for part in parts]
            args = [ffmpeg, "-y", "-loglevel", "error"]
            for part in parts:
                args += ["-i", str(part)]
            args += ["-filter_complex", transition_graph(durations, with_audio), "-map", "[v]"]
            args += ["-map", "[a]", *AUDIO_CODEC] if with_audio else ["-an"]
            args += [*VIDEO_CODEC, "-movflags", "+faststart", str(out)]
            await run_tool(args, timeout=max(120.0, sum(durations) * 8))
        info = await probe_media(out)
        return ComposeResult(out, info.duration, info.has_audio, composed, info.width, info.height)
    finally:
        shutil.rmtree(parts_dir, ignore_errors=True)
