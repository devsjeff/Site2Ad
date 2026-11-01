"""A Magic Hour plan that does not include a resolution is not an empty account: say so, and retry at 480p."""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from app.video.base import VideoError
from app.video.magic_hour import MagicHourProvider, classify_error

from .conftest import make_settings
from .test_video import make_request

PLAN_BODY = "status_code: 402, body: {'code': 'plan_upgrade_required', 'message': 'Resolution 720p is not available for your subscription tier'}"
MODEL_BODY = "status_code: 402, body: {'code': 'plan_upgrade_required', 'message': 'seedance-1.5 is not available for your subscription tier'}"


def test_plan_limits_are_not_reported_as_empty_credits():
    resolution = classify_error(Exception(PLAN_BODY), "secret")
    assert resolution.kind == "plan_resolution" and "480p" in str(resolution) and "credits" not in str(resolution)
    model = classify_error(Exception(MODEL_BODY), "secret")
    assert model.kind == "plan" and "MAGIC_HOUR_MODEL" in str(model)
    assert classify_error(Exception("status_code: 402, body: {'code': 'insufficient_credits', 'message': 'no credits'}"), "secret").kind == "credits"


class OnlyLowResolutionClient:
    """Refuses anything above 480p, like a free Magic Hour plan."""

    calls: list[dict] = []

    def __init__(self, token: str):
        self.v1 = types.SimpleNamespace(text_to_video=types.SimpleNamespace(generate=self._generate))

    def _generate(self, **kw):
        type(self).calls.append(kw)
        if kw["resolution"] != "480p":
            raise Exception(PLAN_BODY)
        target = Path(kw["download_directory"]) / "result.mp4"
        target.write_bytes(b"fake-mp4")
        return types.SimpleNamespace(status="complete", downloaded_paths=[str(target)], credits_charged=240)


async def test_a_resolution_the_plan_lacks_is_retried_at_480p_and_the_user_is_told(tmp_path):
    OnlyLowResolutionClient.calls = []
    provider = MagicHourProvider(make_settings(tmp_path, video_provider="magic_hour", video_model_api_key="not-a-real-key-123"), OnlyLowResolutionClient)
    result = await provider.generate(make_request(tmp_path, None, duration_seconds=5, resolution="720p"))
    assert [call["resolution"] for call in OnlyLowResolutionClient.calls] == ["720p", "480p"]
    assert result.credits_charged == 240 and any("480p" in note and "720p" in note for note in result.notes)


async def test_a_plan_that_refuses_even_480p_fails_clearly_without_a_fake_clip(tmp_path):
    class RefusesEverything(OnlyLowResolutionClient):
        def _generate(self, **kw):
            raise Exception(PLAN_BODY)

    provider = MagicHourProvider(make_settings(tmp_path, video_provider="magic_hour", video_model_api_key="not-a-real-key-123"), RefusesEverything)
    with pytest.raises(VideoError) as info:
        await provider.generate(make_request(tmp_path, None, duration_seconds=5, resolution="720p"))
    assert info.value.kind == "plan_resolution"
