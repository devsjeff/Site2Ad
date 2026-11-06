"""ElevenLabs text-to-speech: studio-quality voices for the voiceover (optional; the free Microsoft voices are the fallback).

The free ElevenLabs plan has 10,000 characters a month, so every line is cached on disk by (voice, model, text): rebuilding a video, or
fixing one shot, never pays for the same sentence twice. When the key is rejected or the plan is used up the engine switches itself
off for the rest of the process and the caller falls back to a Microsoft voice. The API key is never logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional

import httpx

from .base import VideoError

logger = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1/text-to-speech"
TIMEOUT = 60.0
CONCURRENT = 2  # the free plan answers only two requests at a time (more get "too many concurrent requests")
BUSY_RETRIES = 3
MAX_CHARS = 2500  # one line of a voiceover is far shorter; a runaway text is refused instead of eating the monthly allowance

# Voice settings for advertising: lively, close to the script, a little style.
VOICE_SETTINGS = {"stability": 0.42, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}


class ElevenUnavailable(VideoError):
    """The engine cannot be used now (bad key, plan used up): the caller should use another voice."""


class ElevenLabs:
    """One ElevenLabs account. `speak` writes an MP3."""

    def __init__(self, api_key: str, model: str = "eleven_multilingual_v2", cache_dir: Optional[Path] = None):
        self._key = api_key.strip()
        self.model = model or "eleven_multilingual_v2"
        self.cache_dir = cache_dir
        self.off_reason = ""
        self.characters = 0  # paid for in this process (cache hits are free)
        self._gates: dict[int, asyncio.Semaphore] = {}  # one gate per event loop (every video build runs its own loop)

    def _gate(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._gates:
            self._gates = {loop_id: asyncio.Semaphore(CONCURRENT)}
        return self._gates[loop_id]

    @property
    def enabled(self) -> bool:
        return bool(self._key) and not self.off_reason

    def _cached(self, voice_id: str, text: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha1(f"{self.model}|{voice_id}|{text}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.mp3"

    async def speak(self, text: str, voice_id: str, out: Path, *, client: Optional[httpx.AsyncClient] = None) -> None:
        """Write `text` spoken by the ElevenLabs voice `voice_id` to `out`. Raises ElevenUnavailable or VideoError."""
        text = text.strip()
        if not text:
            raise VideoError("there is nothing to say")
        if len(text) > MAX_CHARS:
            raise VideoError("the line is too long for the voice service")
        if not self.enabled:
            raise ElevenUnavailable(self.off_reason or "ElevenLabs is not configured")
        cache = self._cached(voice_id, text)
        if cache is not None and cache.is_file() and cache.stat().st_size > 0:
            shutil.copyfile(cache, out)
            return
        owns = client is None
        http = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            for attempt in range(BUSY_RETRIES + 1):
                try:
                    async with self._gate():
                        response = await http.post(
                            f"{API}/{voice_id}", params={"output_format": "mp3_44100_128"}, headers={"xi-api-key": self._key, "Accept": "audio/mpeg"},
                            json={"text": text, "model_id": self.model, "voice_settings": VOICE_SETTINGS},
                        )
                except httpx.HTTPError as exc:
                    raise VideoError("ElevenLabs could not be reached") from exc
                if response.status_code == 429 and attempt < BUSY_RETRIES and "quota" not in response.text.lower():
                    await asyncio.sleep(1.2 * (attempt + 1))  # busy: wait a moment and ask again
                    continue
                break
        finally:
            if owns:
                await http.aclose()
        self._check(response)
        if not response.content:
            raise VideoError("ElevenLabs returned no audio")
        out.write_bytes(response.content)
        self.characters += len(text)
        if cache is not None:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(out, cache)
            except OSError:  # the cache is a saving, never a requirement
                logger.info("tts cache not written")

    def _check(self, response: httpx.Response) -> None:
        """Turn an error answer into the right exception; a key or quota problem switches the engine off."""
        if response.status_code < 400:
            return
        body = response.text.lower()
        if response.status_code in (401, 403):
            self.off_reason = "ElevenLabs rejected the API key"
            logger.warning(self.off_reason)
            raise ElevenUnavailable(self.off_reason)
        if "quota" in body or response.status_code == 402:
            self.off_reason = "the ElevenLabs plan has no characters left"
            logger.warning(self.off_reason)
            raise ElevenUnavailable(self.off_reason)
        if response.status_code == 429:
            raise VideoError("ElevenLabs is busy (rate limited)")
        logger.warning("ElevenLabs answered with status %s", response.status_code)
        raise VideoError(f"ElevenLabs answered with status {response.status_code}")
