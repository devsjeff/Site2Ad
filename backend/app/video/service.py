"""VideoService: pick the configured provider, fall back to the offline demo provider when the real one fails."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings
from .base import VideoError, VideoProvider, VideoRequest, VideoResult
from .magic_hour import MagicHourProvider
from .mock import MockVideoProvider

logger = logging.getLogger(__name__)


@dataclass
class GenerationOutcome:
    """A raw video plus how it was made."""

    result: VideoResult
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)
    provider_error: str = ""  # why the primary provider failed, kept when a fallback clip was made


# Failures a demo clip cannot fix: the user must act (new key, credits, a valid request), so they fail the ad clearly.
NO_FALLBACK_KINDS = {"auth", "credits", "request"}


def make_provider(settings: Settings) -> VideoProvider:
    """Build the provider chosen by VIDEO_PROVIDER (auto = Magic Hour if a key exists, else the offline demo)."""
    if settings.effective_video_provider == "magic_hour":
        return MagicHourProvider(settings)
    return MockVideoProvider(settings)


class VideoService:
    """Generates ONE raw video for an ad, with an optional automatic fallback."""

    def __init__(self, settings: Settings, primary: Optional[VideoProvider] = None, fallback: Optional[VideoProvider] = None):
        """Providers can be injected for tests."""
        self.settings = settings
        self.primary = primary or make_provider(settings)
        self.fallback = fallback if fallback is not None else (
            MockVideoProvider(settings) if self.primary.name != "mock" and settings.video_fallback_on_error else None
        )

    @property
    def provider_name(self) -> str:
        """Name of the primary provider."""
        return self.primary.name

    async def generate(self, request: VideoRequest) -> GenerationOutcome:
        """Run the primary provider; on failure use the fallback (flagged) or raise VideoError."""
        try:
            return GenerationOutcome(await self.primary.generate(request))
        except VideoError as exc:
            reason = str(exc)
            logger.warning("video provider %s failed (%s): %s", self.primary.name, getattr(exc, "kind", "error"), reason)
            if self.fallback is None or getattr(exc, "kind", "error") in NO_FALLBACK_KINDS:
                raise
        except Exception as exc:  # defensive: provider bugs must not take the pipeline down
            logger.exception("video provider %s crashed", self.primary.name)
            reason = f"unexpected {type(exc).__name__}"
            if self.fallback is None:
                raise VideoError("The video model failed unexpectedly.") from None
        result = await self.fallback.generate(request)
        note = f"The video model could not finish ({reason}). A demo-quality video was created from your image instead."
        return GenerationOutcome(result, fallback_used=True, warnings=[note], provider_error=reason)
