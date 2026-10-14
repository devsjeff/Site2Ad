"""Uploaded media: images (logo, photos) are validated and re-encoded; videos are sniffed and probed. All live under DATA_DIR/assets."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..schemas import AssetInfo
from ..store.db import Database
from ..video.base import VideoError, probe_media
from ..video.images import ImageProblem, prepare_logo, prepare_photo

logger = logging.getLogger(__name__)

ASSET_ID_RE = re.compile(r"^[0-9a-f]{32}$")
VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}
# container sniffed from the first bytes -> (stored extension, words ffprobe must report in format_name)
VIDEO_CONTAINERS = {"mp4": ("mp4", {"mp4", "mov"}), "mov": ("mov", {"mov", "mp4"}), "webm": ("webm", {"webm", "matroska"})}
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
MIN_VIDEO_SIDE = 144
MAX_VIDEO_SIDE = 4096


class VideoUploadProblem(ImageProblem):
    """An uploaded video cannot be used. The message is safe to show to the user."""


def sniff_video(raw: bytes) -> Optional[str]:
    """Container of a video from its magic bytes (never from the file name or the browser's MIME type): mp4, mov, webm or None."""
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return "mov" if raw[8:12] == b"qt  " else "mp4"
    if raw[:4] == b"\x1a\x45\xdf\xa3":  # EBML header (WebM / Matroska)
        return "webm"
    return None


def clean_filename(name: str) -> str:
    """Keep only a short, harmless display name (the stored file never uses it)."""
    base = re.split(r"[\\/]", name or "")[-1]
    return re.sub(r"[^\w.\- ]", "", base)[:80]


class AssetStore:
    """Saves, finds and deletes uploaded images."""

    def __init__(self, settings: Settings, db: Database):
        """Assets live in DATA_DIR/assets; the database keeps one record per file."""
        self.settings = settings
        self.db = db
        self.root = settings.data_dir / "assets"

    async def save(self, raw: bytes, filename: str, kind: str) -> AssetInfo:
        """Validate and store one image or video. Raises ImageProblem (VideoUploadProblem for videos) with a user-safe message."""
        if kind == "video":
            return await self._save_video(raw, filename)
        if kind not in {"logo", "photo"}:
            raise ImageProblem("kind must be 'logo', 'photo' or 'video'.")
        if len(raw) > self.settings.max_upload_bytes:
            raise ImageProblem(f"The file is larger than {self.settings.max_upload_bytes // (1024 * 1024)} MB.")
        asset_id = uuid.uuid4().hex
        suffix = "png" if kind == "logo" else "jpg"
        path = self.root / f"{asset_id}.{suffix}"
        prepared = await asyncio.to_thread(prepare_logo if kind == "logo" else prepare_photo, raw, path)
        size = path.stat().st_size
        await self.db.put(
            "asset", asset_id,
            {"asset_id": asset_id, "kind": kind, "file": path.name, "filename": clean_filename(filename), "width": prepared.width, "height": prepared.height, "bytes": size},
            status=kind,
        )
        return self._info({"asset_id": asset_id, "kind": kind, "filename": clean_filename(filename), "width": prepared.width, "height": prepared.height, "bytes": size})

    async def _save_video(self, raw: bytes, filename: str) -> AssetInfo:
        """Check a video by its bytes and with ffprobe (container, codec, length, size) and store it under a generated name."""
        limit = self.settings.max_video_upload_bytes
        if len(raw) > limit:
            raise VideoUploadProblem(f"The video is larger than {limit // (1024 * 1024)} MB.")
        container = sniff_video(raw)
        if container is None:
            raise VideoUploadProblem("That file is not a supported video. Upload an MP4, MOV or WebM file.")
        extension, expected_formats = VIDEO_CONTAINERS[container]
        asset_id = uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        partial = self.root / f"{asset_id}.part"
        path = self.root / f"{asset_id}.{extension}"
        try:
            await asyncio.to_thread(partial.write_bytes, raw)
            try:
                info = await probe_media(partial)
            except VideoError:
                raise VideoUploadProblem("That file is not a playable video.") from None
            if not expected_formats & set(info.format_name.split(",")):
                raise VideoUploadProblem("The video file does not match its format. Upload an MP4, MOV or WebM file.")
            if info.video_codec not in VIDEO_CODECS:
                raise VideoUploadProblem(f"The video codec '{info.video_codec or 'unknown'}' is not supported. Use H.264, H.265, VP8, VP9 or AV1.")
            if info.duration < 0.5:
                raise VideoUploadProblem("The video is too short (or its length cannot be read).")
            if info.duration > self.settings.max_video_upload_seconds:
                raise VideoUploadProblem(f"The video is longer than {self.settings.max_video_upload_seconds} seconds.")
            if min(info.width, info.height) < MIN_VIDEO_SIDE or max(info.width, info.height) > MAX_VIDEO_SIDE:
                raise VideoUploadProblem(f"The video size {info.width}x{info.height} is not supported (between {MIN_VIDEO_SIDE}px and {MAX_VIDEO_SIDE}px per side).")
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
        record = {
            "asset_id": asset_id, "kind": "video", "file": path.name, "filename": clean_filename(filename), "width": info.width,
            "height": info.height, "bytes": len(raw), "media_type": "video", "duration_seconds": round(info.duration, 2), "has_audio": info.has_audio,
        }
        await self.db.put("asset", asset_id, record, status="video")
        return self._info(record)

    @staticmethod
    def _info(record: dict) -> AssetInfo:
        """Build the public AssetInfo from a record."""
        return AssetInfo(
            asset_id=record["asset_id"], kind=record["kind"], url=f"/api/assets/{record['asset_id']}",
            filename=record.get("filename", ""), width=record.get("width", 0), height=record.get("height", 0), bytes=record.get("bytes", 0),
            media_type=record.get("media_type", "image"), duration_seconds=record.get("duration_seconds", 0.0), has_audio=record.get("has_audio", False),
        )

    @staticmethod
    def media_type(path: Path) -> str:
        """Content type of a stored asset, decided by the extension WE gave it."""
        return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")

    async def find(self, asset_id: str) -> Optional[tuple[AssetInfo, Path]]:
        """Return (info, file path) for an asset id, or None. Malformed ids never touch the filesystem."""
        if not asset_id or not ASSET_ID_RE.match(asset_id):
            return None
        record = await self.db.get("asset", asset_id)
        if not record:
            return None
        path = self.root / record["file"]
        if not path.is_file():
            return None
        return self._info(record), path

    async def delete(self, asset_id: str) -> None:
        """Remove one asset (record and file); unknown ids are ignored."""
        found = await self.find(asset_id)
        if found:
            found[1].unlink(missing_ok=True)
        if ASSET_ID_RE.match(asset_id or ""):
            await self.db.delete("asset", asset_id)

    async def purge_older_than(self, cutoff_ts: float) -> int:
        """Delete assets created before the cutoff (files and records). Returns how many were removed."""
        records = await self.db.pop_older_than("asset", cutoff_ts)
        for record in records:
            (self.root / record.get("file", "missing")).unlink(missing_ok=True)
        return len(records)
