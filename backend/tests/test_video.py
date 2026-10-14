"""Video layer tests: hero preparation, safe image download, demo provider, Magic Hour adapter, overlays, fallback."""

from __future__ import annotations

import io
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from app.scraper.fetch import Fetcher
from app.scraper.safety import build_http_client
from app.video.base import VideoError, VideoRequest, output_size, probe_video, scrub
from app.video.finalize import OverlaySpec, finalize_video, render_overlay, wrap_text
from app.video.images import ImageProblem, cover_crop, download_image, prepare_hero, prepare_logo, sniff_extension
from app.video.magic_hour import MagicHourProvider
from app.video.mock import MockVideoProvider
from app.video.service import VideoService

from .conftest import LOCAL_POLICY, make_settings
from .fixture_server import FixtureServer, Route


def png_bytes(size=(1200, 800), color=(200, 80, 40), mode="RGB") -> bytes:
    """A solid colour PNG."""
    buffer = io.BytesIO()
    Image.new(mode, size, color if mode == "RGB" else color + (255,)).save(buffer, "PNG")
    return buffer.getvalue()


def make_request(tmp_path: Path, image: Path | None, **kw) -> VideoRequest:
    """A VideoRequest with sensible defaults."""
    base = dict(
        ad_id="ad1", prompt="Create ONE ad\n\nNEGATIVE PROMPT: x", negative_prompt="x", image_path=image, duration_seconds=2,
        aspect_ratio="16:9", resolution="480p", output_dir=tmp_path / "out", business_name="Sharma Sweets", accent_color="#c0392b",
    )
    base.update(kw)
    return VideoRequest(**base)


# --------------------------------------------------------------------------- sizes and images


def test_output_sizes_are_even_and_match_the_aspect():
    """Check: output sizes are even and match the aspect."""
    assert output_size("16:9", "480p") == (854, 480)
    assert output_size("9:16", "480p") == (480, 854)
    assert output_size("1:1", "720p") == (720, 720)
    assert output_size("weird", "bad") == (854, 480)


def test_scrub_hides_secrets_and_limits_length():
    """Check: scrub hides secrets and limits length."""
    text = scrub("failed with key sk-secret-1 \n and more " + "x" * 400, "sk-secret-1")
    assert "sk-secret-1" not in text and "***" in text and len(text) <= 240 and "\n" not in text


def test_cover_crop_keeps_target_ratio_without_stretching():
    """Check: cover crop keeps target ratio without stretching."""
    wide = Image.new("RGB", (1600, 900))
    assert cover_crop(wide, "9:16").size == (506, 900)
    tall = Image.new("RGB", (900, 1600))
    assert cover_crop(tall, "16:9").size == (900, 506)
    assert cover_crop(Image.new("RGB", (800, 800)), "1:1").size == (800, 800)


def test_prepare_hero_crops_saves_jpeg_and_reports_size(tmp_path):
    """Check: prepare hero crops saves jpeg and reports size."""
    prepared = prepare_hero(png_bytes((1600, 900)), tmp_path / "hero.jpg", "9:16", min_side=400)
    assert prepared.path.suffix == ".jpg" and prepared.source_width == 1600
    with Image.open(prepared.path) as image:
        assert image.format == "JPEG" and image.size == (prepared.width, prepared.height)
        assert abs(image.width / image.height - 9 / 16) < 0.01
    assert prepared.warnings == []


def test_prepare_hero_flattens_transparency_and_warns_when_small(tmp_path):
    """Check: prepare hero flattens transparency and warns when small."""
    prepared = prepare_hero(png_bytes((300, 300), (10, 20, 30), mode="RGBA"), tmp_path / "h.jpg", "1:1", min_side=400)
    assert prepared.warnings and "small" in prepared.warnings[0]


def test_prepare_hero_rejects_bad_files(tmp_path):
    """Check: prepare hero rejects bad files."""
    out = tmp_path / "h.jpg"
    with pytest.raises(ImageProblem, match="SVG"):
        prepare_hero(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', out, "16:9", min_side=400)
    with pytest.raises(ImageProblem, match="readable"):
        prepare_hero(b"<html>not an image</html>", out, "16:9", min_side=400)
    with pytest.raises(ImageProblem, match="too small"):
        prepare_hero(png_bytes((100, 100)), out, "16:9", min_side=400)
    assert not out.exists()


def test_prepare_logo_makes_a_small_transparent_png(tmp_path):
    """Check: prepare logo makes a small transparent png."""
    prepared = prepare_logo(png_bytes((2000, 1000), (0, 0, 0), mode="RGBA"), tmp_path / "logo.png")
    assert max(prepared.width, prepared.height) <= 512
    with Image.open(prepared.path) as image:
        assert image.mode == "RGBA"


def test_sniff_extension():
    """Check: sniff extension."""
    assert sniff_extension(png_bytes()) == "png"
    assert sniff_extension(b"nope") is None


# --------------------------------------------------------------------------- safe download


def image_site() -> FixtureServer:
    """A server with a good image, a page, a big file and a redirect to a private address."""
    routes = {
        "/ok.png": Route(body=png_bytes(), content_type="image/png"),
        "/page": Route(body="<html>hi</html>"),
        "/huge.png": Route(body=b"", content_type="image/png", stream_bytes=3_000_000),
        "/missing.png": Route(body="x", status=404, content_type="text/plain"),
        "/evil.png": Route(body="", status=302, headers={"Location": "http://169.254.169.254/latest/meta-data"}),
    }
    return FixtureServer(routes)


async def test_download_image_is_safe_and_explains_failures():
    """Check: download image is safe and explains failures."""
    settings = make_settings()
    async with build_http_client(settings, LOCAL_POLICY) as client:
        fetcher = Fetcher(client, settings, LOCAL_POLICY)
        with image_site() as site:
            raw = await download_image(fetcher, site.base + "/ok.png", max_bytes=1_000_000)
            assert raw[:4] == b"\x89PNG"
            for path, fragment in (("/page", "not an image"), ("/huge.png", "too large"), ("/missing.png", "status 404"), ("/evil.png", "not allowed")):
                with pytest.raises(ImageProblem, match=fragment):
                    await download_image(fetcher, site.base + path, max_bytes=1_000_000)
        with pytest.raises(ImageProblem, match="not allowed"):
            await download_image(fetcher, "http://10.0.0.5/a.png", max_bytes=1_000_000)


# --------------------------------------------------------------------------- providers


async def test_mock_provider_makes_a_real_video_with_and_without_an_image(tmp_path):
    """Check: mock provider makes a real video with and without an image."""
    provider = MockVideoProvider(make_settings(tmp_path))
    hero = tmp_path / "hero.jpg"
    Image.new("RGB", (854, 480), (30, 120, 200)).save(hero)
    with_image = await provider.generate(make_request(tmp_path, hero))
    info = await probe_video(with_image.path)
    assert (info.width, info.height) == (854, 480) and 1.5 < info.duration < 2.6
    assert with_image.provider == "mock"
    vertical = await provider.generate(make_request(tmp_path, None, aspect_ratio="9:16", ad_id="ad2"))
    info2 = await probe_video(vertical.path)
    assert (info2.width, info2.height) == (480, 854)


class FakeMagicHourClient:
    """Stands in for magic_hour.Client; records the call and 'downloads' a file."""

    calls: list[dict] = []
    status = "complete"
    error: Exception | None = None

    def __init__(self, token: str):
        """Remember the token the way the SDK does."""
        self.token = token
        self.v1 = types.SimpleNamespace(
            image_to_video=types.SimpleNamespace(generate=lambda **kw: self._generate(endpoint="image_to_video", **kw)),
            text_to_video=types.SimpleNamespace(generate=lambda **kw: self._generate(endpoint="text_to_video", **kw)),
        )

    def _generate(self, **kw):
        """Fake SDK call."""
        type(self).calls.append(kw)
        if self.error:
            raise self.error
        target = Path(kw["download_directory"]) / "result.mp4"
        target.write_bytes(b"fake-mp4")
        return types.SimpleNamespace(status=self.status, downloaded_paths=[str(target)], credits_charged=450)


@pytest.fixture
def magic_hour(tmp_path):
    """A MagicHourProvider wired to the fake SDK client."""
    FakeMagicHourClient.calls = []
    FakeMagicHourClient.status = "complete"
    FakeMagicHourClient.error = None
    settings = make_settings(tmp_path, video_provider="magic_hour", video_model_api_key="not-a-real-key-123")
    hero = tmp_path / "hero.jpg"
    Image.new("RGB", (854, 480)).save(hero)
    return MagicHourProvider(settings, FakeMagicHourClient), hero, tmp_path


async def test_magic_hour_sends_one_prompt_and_one_image(magic_hour):
    """Check: magic hour sends one prompt and one image."""
    provider, hero, tmp_path = magic_hour
    result = await provider.generate(make_request(tmp_path, hero, duration_seconds=5))
    assert result.path.read_bytes() == b"fake-mp4" and result.credits_charged == 450 and result.provider == "magic_hour"
    (call,) = FakeMagicHourClient.calls
    assert call["endpoint"] == "image_to_video" and call["assets"] == {"image_file_path": str(hero)}
    assert call["style"] == {"prompt": "Create ONE ad\n\nNEGATIVE PROMPT: x"}
    assert call["model"] == "ltx-2.5" and call["end_seconds"] == 5 and call["resolution"] == "480p"
    assert call["wait_for_completion"] is True and call["download_outputs"] is True
    assert not (tmp_path / "out" / "ad1.mh").exists()  # temp download dir is cleaned up


async def test_magic_hour_without_an_image_uses_text_to_video(magic_hour):
    """AI Video Priority sends no image: the footage is generated from the prompt alone (no website picture in it)."""
    provider, _hero, tmp_path = magic_hour
    result = await provider.generate(make_request(tmp_path, None, duration_seconds=5))
    assert result.provider == "magic_hour"
    (call,) = FakeMagicHourClient.calls
    assert call["endpoint"] == "text_to_video" and "assets" not in call
    assert call["style"] == {"prompt": "Create ONE ad\n\nNEGATIVE PROMPT: x"} and call["aspect_ratio"] == "16:9" and call["end_seconds"] == 5


async def test_magic_hour_clamps_duration_to_the_configured_maximum(magic_hour):
    """Check: magic hour clamps duration to the configured maximum."""
    provider, hero, tmp_path = magic_hour
    await provider.generate(make_request(tmp_path, hero, duration_seconds=20))
    assert FakeMagicHourClient.calls[0]["end_seconds"] == 5


async def test_magic_hour_failures_become_safe_video_errors(magic_hour):
    """Check: magic hour failures become safe video errors."""
    provider, hero, tmp_path = magic_hour
    FakeMagicHourClient.status = "error"
    with pytest.raises(VideoError, match="status 'error'"):
        await provider.generate(make_request(tmp_path, hero))
    FakeMagicHourClient.status = "complete"
    FakeMagicHourClient.error = RuntimeError("402 payment required for token not-a-real-key-123")
    with pytest.raises(VideoError) as info:
        await provider.generate(make_request(tmp_path, hero))
    assert "not-a-real-key-123" not in str(info.value) and "payment required" in str(info.value)
    with pytest.raises(VideoError, match="first-frame image"):
        await provider.generate(make_request(tmp_path, tmp_path / "missing.jpg"))
    no_key = MagicHourProvider(make_settings(tmp_path), FakeMagicHourClient)
    with pytest.raises(VideoError, match="VIDEO_MODEL_API_KEY"):
        await no_key.generate(make_request(tmp_path, hero))


class FailingProvider:
    """A provider that always fails."""

    name = "failing"

    async def generate(self, request):
        """Always raise."""
        raise VideoError("model is down")


async def test_service_falls_back_to_the_demo_provider_and_says_so(tmp_path):
    """Check: service falls back to the demo provider and says so."""
    settings = make_settings(tmp_path)
    service = VideoService(settings, primary=FailingProvider())
    outcome = await service.generate(make_request(tmp_path, None))
    assert outcome.fallback_used is True and outcome.result.provider == "mock"
    assert "model is down" in outcome.warnings[0]


async def test_service_without_fallback_raises(tmp_path):
    """Check: service without fallback raises."""
    service = VideoService(make_settings(tmp_path, video_fallback_on_error=False), primary=FailingProvider())
    with pytest.raises(VideoError, match="model is down"):
        await service.generate(make_request(tmp_path, None))


async def test_service_mock_primary_has_no_fallback_and_no_flag(tmp_path):
    """Check: service mock primary has no fallback and no flag."""
    service = VideoService(make_settings(tmp_path))
    assert service.provider_name == "mock" and service.fallback is None
    outcome = await service.generate(make_request(tmp_path, None))
    assert outcome.fallback_used is False and outcome.warnings == []


# --------------------------------------------------------------------------- overlays


def alpha_in(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    """Highest alpha value in a region."""
    return image.crop(box).getchannel("A").getextrema()[1]


def test_render_overlay_places_text_logo_and_qr(tmp_path, monkeypatch):
    """Check: render overlay places text logo and qr."""
    fake_qr = types.SimpleNamespace(make=lambda url: Image.new("RGB", (41, 41), (0, 0, 0)))
    monkeypatch.setitem(sys.modules, "qrcode", fake_qr)
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(logo)
    spec = OverlaySpec(name="Sharma Sweets", offer="Diwali offer: 20% off", cta="Order Now", phone="+91 98765 43210", address="12 Gandhi Chowk", qr_url="https://sharmasweets.example", logo_path=logo)
    out = tmp_path / "overlay.png"
    warnings = render_overlay(854, 480, spec, out)
    assert warnings == []
    with Image.open(out) as overlay:
        assert overlay.size == (854, 480)
        assert alpha_in(overlay, (10, 300, 400, 470)) > 0  # text panel bottom-left
        assert alpha_in(overlay, (700, 330, 840, 470)) == 255  # QR backing bottom-right
        assert alpha_in(overlay, (10, 10, 150, 80)) > 0  # logo top-left
        assert alpha_in(overlay, (300, 10, 700, 100)) == 0  # nothing in the top middle


def test_render_overlay_skips_missing_pieces_and_warns_without_qrcode(tmp_path, monkeypatch):
    """Check: render overlay skips missing pieces and warns without qrcode."""
    monkeypatch.setitem(sys.modules, "qrcode", None)  # makes `import qrcode` raise ImportError
    out = tmp_path / "o.png"
    warnings = render_overlay(480, 854, OverlaySpec(name="Quiet Books", qr_url="https://quiet.example"), out)
    assert any("qrcode" in w for w in warnings)
    with Image.open(out) as overlay:
        assert alpha_in(overlay, (0, 0, 480, 400)) == 0  # no phone/address/logo, nothing at the top
        assert alpha_in(overlay, (10, 700, 300, 850)) > 0


def test_wrap_text_wraps_and_cuts_with_an_ellipsis():
    """Check: wrap text wraps and cuts with an ellipsis."""
    from PIL import ImageDraw
    from app.video.finalize import load_font

    draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    font = load_font(20, False)
    lines = wrap_text(draw, "one two three four five six seven eight nine ten", font, 200, 2)
    assert len(lines) == 2 and lines[1].endswith("…")
    assert all(draw.textlength(line, font=font) <= 200 for line in lines)
    assert wrap_text(draw, "short", font, 200, 2) == ["short"]


async def test_finalize_writes_a_playable_video_with_overlays(tmp_path):
    """Check: finalize writes a playable video with overlays."""
    raw = (await MockVideoProvider(make_settings(tmp_path)).generate(make_request(tmp_path, None))).path
    final = tmp_path / "final.mp4"
    result = await finalize_video(raw, final, OverlaySpec(name="Sharma Sweets", phone="+91 98765 43210"))
    assert result.applied is True and final.is_file()
    info = await probe_video(final)
    assert (info.width, info.height) == (854, 480)
    assert final.read_bytes() != raw.read_bytes()


async def test_finalize_without_anything_to_draw_copies_the_video(tmp_path):
    """Check: finalize without anything to draw copies the video."""
    raw = (await MockVideoProvider(make_settings(tmp_path)).generate(make_request(tmp_path, None))).path
    final = tmp_path / "final.mp4"
    result = await finalize_video(raw, final, OverlaySpec())
    assert result.applied is False and final.read_bytes() == raw.read_bytes()


async def test_finalize_keeps_the_video_when_ffmpeg_fails(tmp_path):
    """Check: finalize keeps the video when ffmpeg fails."""
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"this is not a video")
    final = tmp_path / "final.mp4"
    result = await finalize_video(broken, final, OverlaySpec(name="X"))
    assert result.applied is False and final.read_bytes() == b"this is not a video"
    assert result.warnings and "without them" in result.warnings[0]
