"""Creative modes end to end: manual, website, AI, website + AI. Real FFmpeg and real local media; AI calls are mocked.

Every test also checks what must NOT run: the scraper for manual ads, the prompt writer and the AI video provider for
manual and website ads, and website pictures in AI-only ads.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from pydantic import ValidationError

from app.ai.facts import MissingBusinessName
from app.ai.prompt_builder import PromptBuilder
from app.api.core import Api, ApiError, UploadedFile
from app.context import AppContext
from app.schemas import AdOptions, BusinessOverrides, CreativeConfig, GenerateAdRequest, HeroRef, ScrapeResult, SiteInfo
from app.scraper.render import BrowserPool, RenderResult
from app.scraper.service import Scraper
from app.services.ads import CANCELLED_MESSAGE, AiVideoUnavailable, InvalidCreative, UnknownJob, website_slots
from app.video import finalize as finalize_module
from app.video.base import VideoError, VideoResult, ffmpeg_path, output_size, probe_media
from app.video.service import VideoService

from .conftest import LOCAL_POLICY, make_settings
from .fixture_server import FixtureServer, Route, html
from .test_pipeline import finished_ad, png, scan, sweets_with_images

FRONTEND_FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "creative.fixtures.json"
QR_URL = "https://sharmasweets.example/order?src=taxi"


# --------------------------------------------------------------------------- fakes and helpers


class CountingProvider:
    """A fake AI video provider: makes a solid blue clip with FFmpeg and counts how often it is called."""

    def __init__(self, name: str = "fake_ai", seconds: float | None = None, fail: bool = False, delay: float = 0.0):
        """`seconds` makes the clip shorter than requested; `fail` raises like a provider outage."""
        self.name = name
        self.seconds = seconds
        self.fail = fail
        self.delay = delay
        self.calls: list = []

    async def generate(self, request):
        """Record the request and return a real MP4."""
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise VideoError("model is down")
        width, height = output_size(request.aspect_ratio, request.resolution)
        seconds = self.seconds or request.duration_seconds
        out = request.output_dir / f"{request.ad_id}.raw.mp4"
        await asyncio.to_thread(subprocess.run, [
            ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=blue:s={width}x{height}:r=24", "-t", str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
        ], check=True)
        return VideoResult(path=out, provider=self.name, duration_seconds=float(seconds))


class CountingPrompts(PromptBuilder):
    """The real prompt builder, counting its calls."""

    def __init__(self, settings):
        """Start at zero."""
        super().__init__(settings)
        self.calls = 0

    async def build(self, *args, **kwargs):
        """Count, then build as usual."""
        self.calls += 1
        return await super().build(*args, **kwargs)

    async def build_scene(self, *args, **kwargs):
        """Count, then build the scene prompt as usual."""
        self.calls += 1
        return await super().build_scene(*args, **kwargs)


class CountingScraper(Scraper):
    """The real scraper (local fixtures only), counting scans."""

    def __init__(self, settings, **kw):
        """Start at zero."""
        super().__init__(settings, policy=LOCAL_POLICY, **kw)
        self.scans = 0

    async def scrape_phase1(self, *args, **kwargs):
        """Count, then scan as usual."""
        self.scans += 1
        return await super().scrape_phase1(*args, **kwargs)


@asynccontextmanager
async def creative_ctx(tmp_path, provider=None, pool=None, **overrides):
    """An AppContext whose scraper, prompt builder and video provider all count their calls."""
    settings = make_settings(tmp_path, **overrides)
    provider = provider or CountingProvider()
    video = VideoService(settings, primary=provider)
    prompts = CountingPrompts(settings)
    scraper = CountingScraper(settings, pool=pool) if pool else CountingScraper(settings)
    ctx = await AppContext.create(settings, scraper=scraper, prompts=prompts, video=video, start_background=False)
    try:
        yield ctx, provider, prompts, scraper
    finally:
        await ctx.close()


@asynccontextmanager
async def _served(routes):
    """Serve fixture routes for an `async with` block."""
    with FixtureServer(routes) as site:
        yield site


def make_video(path: Path, seconds: float = 2.0, *, audio: bool = True, codec: str = "libx264", size: str = "640x360") -> bytes:
    """A real test video (colour bars, optional 440 Hz tone) and its bytes."""
    args = [ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
    args += ["-t", str(seconds), "-c:v", codec]
    if codec == "libx264":
        args += ["-pix_fmt", "yuv420p"]
    args += (["-c:a", "aac"] if audio else []) + [str(path)]
    subprocess.run(args, check=True)
    return path.read_bytes()


def frame_at(video: Path, seconds: float, out: Path) -> Image.Image:
    """One decoded frame of a video as an RGB image."""
    subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-ss", f"{seconds:.2f}", "-i", str(video), "-frames:v", "1", str(out)], check=True)
    with Image.open(out) as image:
        return image.convert("RGB").copy()


def centre(image: Image.Image) -> tuple[int, int, int]:
    """Average colour of a small box in the middle of a frame (away from every overlay)."""
    w, h = image.size
    box = image.crop((w // 2 - 10, h // 2 - 10, w // 2 + 10, h // 2 + 10)).resize((1, 1), Image.Resampling.BOX)
    return box.getpixel((0, 0))


def close(colour, expected, tolerance: int = 40) -> bool:
    """True when two RGB colours are near each other (video compression shifts them a little)."""
    return all(abs(a - b) <= tolerance for a, b in zip(colour, expected))


def qr_backing_brightness(image: Image.Image) -> float:
    """Mean brightness of the white border that finalize.py draws around a QR code (bottom-right)."""
    width, height = image.size
    unit = min(width, height)
    margin, qr_size, backing = max(12, round(unit * 0.04)), max(96, round(unit * 0.24)), max(6, round(unit * 0.012))
    qx, qy = width - margin - qr_size, height - margin - qr_size
    strip = image.crop((qx - backing + 2, qy + qr_size // 4, qx - 1, qy + 3 * qr_size // 4)).convert("L")
    return ImageStat.Stat(strip).mean[0]


def spy_qr(monkeypatch) -> list[str]:
    """Record every URL that is turned into a QR code."""
    seen: list[str] = []
    original = finalize_module._make_qr

    def recording(url):
        """Record, then draw the real QR code."""
        seen.append(url)
        return original(url)

    monkeypatch.setattr(finalize_module, "_make_qr", recording)
    return seen


def manual(asset_ids, **kw) -> CreativeConfig:
    """A manual creative configuration."""
    return CreativeConfig(creation_mode="manual", use_uploaded_media=True, media_asset_ids=asset_ids, **kw)


def auto(mode: str, **kw) -> CreativeConfig:
    """An auto creative configuration with the defaults the UI uses for that mode."""
    flags = {"website": dict(use_website_images=True), "ai": dict(use_ai_video=True), "mixed": dict(use_website_images=True, use_ai_video=True)}[mode]
    return CreativeConfig(creation_mode="auto", creative_mode=mode, **{**flags, **kw})


async def _api_error(coro) -> ApiError:
    """Await something that must raise ApiError."""
    with pytest.raises(ApiError) as info:
        await coro
    return info.value


async def _blocked_result(ctx):
    """The scan result of a Cloudflare-blocked site (no facts, no images)."""
    from .sites import cloudflare_challenge

    async with _served(cloudflare_challenge()) as site:
        return (await scan(ctx, site.base)).result


# --------------------------------------------------------------------------- manual ads


async def test_manual_image_upload_becomes_mp4_with_the_exact_qr(tmp_path, monkeypatch):
    """Manual image upload -> FFmpeg -> QR -> final MP4; no scan, no prompt writer, no AI video."""
    seen = spy_qr(monkeypatch)
    async with creative_ctx(tmp_path) as (ctx, provider, prompts, scraper):
        photo = await ctx.assets.save(png((1200, 800), (20, 20, 20)), "shop.png", "photo")
        request = GenerateAdRequest(
            business=BusinessOverrides(name="Night Owl Cafe", offer="2 for 1 coffee", cta="Scan to order"),
            options=AdOptions(platform="taxi_screen", duration_seconds=5),
            creative=manual([photo.asset_id], include_qr=True, qr_url=f"  {QR_URL}  "),
        )
        ad = await ctx.ads.create(request)
        assert ad.provider == "ffmpeg" and ad.prompt is None and ad.creative.qr_url == QR_URL
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed", done.error
        assert done.qr_added is True and done.ai_video_used is False and done.prompt is None
        assert [s.kind for s in done.composition] == ["uploaded_image"]
        assert seen == [QR_URL]  # exactly the user's URL, nothing invented
        path = ctx.ads.video_path(ad.ad_id)
        info = await probe_media(path)
        assert (info.width, info.height) == (1280, 720) and 4.5 <= info.duration <= 5.5
        assert qr_backing_brightness(frame_at(path, 2.0, tmp_path / "f.png")) > 200
        assert provider.calls == [] and prompts.calls == 0 and scraper.scans == 0


async def test_manual_video_keeps_its_content_and_sound_without_ai(tmp_path):
    """Manual video upload -> FFmpeg finalization; audio kept; no AI calls."""
    async with creative_ctx(tmp_path) as (ctx, provider, prompts, scraper):
        raw = make_video(tmp_path / "clip.mp4", 2.0, audio=True)
        video = await ctx.assets.save(raw, "clip.mp4", "video")
        assert video.kind == "video" and video.media_type == "video" and video.has_audio and 1.8 <= video.duration_seconds <= 2.2
        photo = await ctx.assets.save(png((800, 800), (200, 30, 30)), "p.png", "photo")
        request = GenerateAdRequest(
            business=BusinessOverrides(name="Clip Shop"), options=AdOptions(platform="instagram_reel", duration_seconds=10),
            creative=manual([video.asset_id, photo.asset_id], include_logo=False),
        )
        done = await finished_ad(ctx, (await ctx.ads.create(request)).ad_id)
        assert done.status == "completed", done.error
        assert [s.kind for s in done.composition] == ["uploaded_video", "uploaded_image"]
        assert any("full length" in w for w in done.warnings)  # honest about the real length
        info = await probe_media(ctx.ads.video_path(done.ad_id))
        assert info.has_audio and (info.width, info.height) == (720, 1280) and 4.5 <= info.duration <= 5.5
        assert provider.calls == [] and prompts.calls == 0 and scraper.scans == 0

        silent = GenerateAdRequest(options=AdOptions(add_overlays=False), creative=manual([video.asset_id], keep_audio=False))
        done = await finished_ad(ctx, (await ctx.ads.create(silent)).ad_id)
        assert done.status == "completed" and not (await probe_media(ctx.ads.video_path(done.ad_id))).has_audio


async def test_qr_disabled_means_no_qr_overlay(tmp_path, monkeypatch):
    """QR disabled -> no QR code is generated or drawn."""
    seen = spy_qr(monkeypatch)
    async with creative_ctx(tmp_path) as (ctx, *_):
        photo = await ctx.assets.save(png((1200, 800), (20, 20, 20)), "shop.png", "photo")
        request = GenerateAdRequest(business=BusinessOverrides(name="No QR Cafe"), creative=manual([photo.asset_id], include_qr=False))
        done = await finished_ad(ctx, (await ctx.ads.create(request)).ad_id)
        assert done.status == "completed" and done.qr_added is False and seen == []
        assert qr_backing_brightness(frame_at(ctx.ads.video_path(done.ad_id), 2.0, tmp_path / "f.png")) < 80


async def test_qr_failure_is_reported_not_claimed(tmp_path, monkeypatch):
    """A QR code that cannot be generated is a warning and qr_added stays false."""
    def broken(url):
        """Simulate a QR library failure."""
        raise finalize_module.QrUnavailable("QR code skipped because it could not be generated for that address.")

    monkeypatch.setattr(finalize_module, "_make_qr", broken)
    async with creative_ctx(tmp_path) as (ctx, *_):
        photo = await ctx.assets.save(png(), "p.png", "photo")
        done = await finished_ad(ctx, (await ctx.ads.create(GenerateAdRequest(creative=manual([photo.asset_id], include_qr=True, qr_url=QR_URL)))).ad_id)
        assert done.status == "completed" and done.qr_added is False
        assert any(w.startswith("QR code") for w in done.warnings)


# --------------------------------------------------------------------------- website content


def test_website_slots_are_three_seconds_each():
    """Website ads show each image for 3 s: 5 s -> 2 images, 15 s -> 5, 20 s -> 7 (6 x 3 s + 2 s)."""
    assert website_slots(5) == [3.0, 2.0]
    assert website_slots(10) == [3.0, 3.0, 4.0]
    assert website_slots(15) == [3.0] * 5
    assert website_slots(20) == [3.0] * 6 + [2.0]


async def test_website_mode_uses_original_images_and_never_calls_ai(tmp_path):
    """Website mode -> HTTPX scan -> original images, 3 s each -> FFmpeg; zero prompt-writer and AI video calls."""
    async with creative_ctx(tmp_path) as (ctx, provider, prompts, scraper), _served(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        assert job.result.meta.rendered_with == "httpx"
        a, b = [u for u in job.result.images if u.endswith(("/img/a.jpg", "/img/b.jpg"))]
        request = GenerateAdRequest(
            job_id=job.job_id, options=AdOptions(duration_seconds=6),
            creative=auto("website", selected_image_urls=[a, b], include_qr=True, qr_url=QR_URL),
        )
        ad = await ctx.ads.create(request)
        assert ad.provider == "ffmpeg" and ad.prompt is None
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed", done.error
        assert [(s.kind, s.source, s.seconds) for s in done.composition] == [("website_image", a, 3.0), ("website_image", b, 3.0)]
        assert done.qr_added and not done.ai_video_used and done.prompt is None
        path = ctx.ads.video_path(ad.ad_id)
        assert 5.5 <= (await probe_media(path)).duration <= 6.5
        assert close(centre(frame_at(path, 1.0, tmp_path / "1.png")), (210, 90, 40))  # the original a.jpg colours
        assert close(centre(frame_at(path, 4.5, tmp_path / "2.png")), (30, 140, 90))  # then the original b.jpg
        assert provider.calls == [] and prompts.calls == 0


async def test_website_mode_loops_one_image_every_three_seconds(tmp_path):
    """One website image and a 15 s ad -> the same original image 5 times, 3 s each."""
    async with creative_ctx(tmp_path) as (ctx, provider, prompts, _), _served(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        a = next(u for u in job.result.images if u.endswith("/img/a.jpg"))
        request = GenerateAdRequest(job_id=job.job_id, options=AdOptions(duration_seconds=15), creative=auto("website", selected_image_urls=[a]))
        done = await finished_ad(ctx, (await ctx.ads.create(request)).ad_id)
        assert done.status == "completed", done.error
        assert [(s.source, s.seconds) for s in done.composition] == [(a, 3.0)] * 5
        assert any("repeats" in w for w in done.warnings)
        assert 14.5 <= (await probe_media(ctx.ads.video_path(done.ad_id))).duration <= 15.5
        assert provider.calls == [] and prompts.calls == 0


async def test_website_mode_loops_several_images_in_order(tmp_path):
    """Two images, 10 s -> a, b, a (3 s, 3 s, 4 s)."""
    async with creative_ctx(tmp_path) as (ctx, *_), _served(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        a, b = [u for u in job.result.images if u.endswith(("/img/a.jpg", "/img/b.jpg"))]
        request = GenerateAdRequest(job_id=job.job_id, options=AdOptions(duration_seconds=10), creative=auto("website", selected_image_urls=[a, b]))
        done = await finished_ad(ctx, (await ctx.ads.create(request)).ad_id)
        assert [(s.source, s.seconds) for s in done.composition] == [(a, 3.0), (b, 3.0), (a, 4.0)]


def csr_site(with_og_image: bool = False) -> dict:
    """A JavaScript-only shop (empty #root). The raw HTML may carry one og:image; the rendered page has two photos."""
    og = '<meta property="og:image" content="/img/og.jpg">' if with_og_image else ""
    return {
        "/": html(f"""<!doctype html><html><head><title>React App</title>{og}</head><body>
<noscript>You need to enable JavaScript to run this app.</noscript><div id="root"></div><script>/* app */</script></body></html>"""),
        "/img/cafe1.jpg": Route(body=png((900, 600), (200, 40, 160)), content_type="image/png"),
        "/img/cafe2.jpg": Route(body=png((900, 600), (40, 160, 200)), content_type="image/png"),
        "/img/og.jpg": Route(body=png((1200, 630), (230, 200, 30)), content_type="image/png"),
        "/robots.txt": Route(body="User-agent: *\n", content_type="text/plain"),
    }


RENDERED = """<!doctype html><html><head><title>Green Leaf Cafe</title></head><body><main><h1>Green Leaf Cafe</h1>
<p>{text}</p><img src="/img/cafe1.jpg" width="900" height="600"><img src="/img/cafe2.jpg" width="900" height="600"></main>
<footer><a href="tel:+917712345678">+91 77123 45678</a></footer></body></html>"""


class FakeBrowserPool(BrowserPool):
    """A Playwright pool that 'renders' the JavaScript shell into the finished page (no real browser needed)."""

    def __init__(self, settings):
        """Count renders."""
        super().__init__(settings, LOCAL_POLICY)
        self.renders = 0

    async def render(self, url, deadline):
        """Return the page as the browser would see it after the scripts ran."""
        self.renders += 1
        text = "Organic coffee, fresh salads and homemade cakes in the heart of Raipur. " * 4
        return RenderResult(True, url, html=RENDERED.format(text=text), status_code=200)

    @property
    def engine_name(self) -> str:
        """Pretend engine."""
        return "firefox"


async def test_csr_website_is_rendered_with_playwright_when_available(tmp_path):
    """CSR website -> Playwright renderer (when available) -> its images reach the website-mode ad."""
    pool = FakeBrowserPool(make_settings(tmp_path))
    async with creative_ctx(tmp_path, pool=pool) as (ctx, provider, prompts, _), _served(csr_site()) as site:
        job = await scan(ctx, site.base)
        result = job.result
        assert "spa_site" in result.flags and result.meta.rendered_with == "playwright" and pool.renders >= 1
        assert result.site.name == "Green Leaf Cafe" and any(u.endswith("/img/cafe1.jpg") for u in result.images)
        done = await finished_ad(ctx, (await ctx.ads.create(GenerateAdRequest(job_id=job.job_id, creative=auto("website")))).ad_id)
        assert done.status == "completed", done.error
        assert [s.source.rsplit("/", 1)[-1] for s in done.composition] == ["cafe1.jpg", "cafe2.jpg"]
        assert not any("Playwright" in w for w in done.warnings)
        assert provider.calls == [] and prompts.calls == 0


async def test_csr_website_falls_back_to_httpx_with_a_warning_without_playwright(tmp_path):
    """CSR website without Playwright -> the plain HTML result is used and the user is told content may be missing."""
    async def no_playwright():
        """Playwright is not installed."""
        raise ModuleNotFoundError("playwright")

    pool = BrowserPool(make_settings(tmp_path), LOCAL_POLICY, playwright_factory=no_playwright)
    async with creative_ctx(tmp_path, pool=pool) as (ctx, provider, _, _s), _served(csr_site(with_og_image=True)) as site:
        job = await scan(ctx, site.base)
        assert job.result.status == "partial" and "browser_unavailable" in job.result.flags
        assert job.result.meta.rendered_with == "httpx"
        request = GenerateAdRequest(job_id=job.job_id, business=BusinessOverrides(name="Green Leaf Cafe"), creative=auto("website"))
        ad = await ctx.ads.create(request)
        assert any("Playwright" in w and "may be missing" in w for w in ad.warnings)
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed", done.error
        assert [s.source.rsplit("/", 1)[-1] for s in done.composition] == ["og.jpg", "og.jpg"]  # 5 s = 3 s + 2 s, one image loops
        assert provider.calls == []


# --------------------------------------------------------------------------- AI and mixed


async def test_ai_mode_is_ai_footage_only_from_scraped_facts(tmp_path, monkeypatch):
    """AI mode -> prompt from the scraped facts -> text-to-video (no image sent) -> finalize with the user's QR."""
    seen = spy_qr(monkeypatch)
    async with creative_ctx(tmp_path) as (ctx, provider, prompts, _), _served(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        request = GenerateAdRequest(job_id=job.job_id, options=AdOptions(duration_seconds=5), creative=auto("ai", include_qr=True, qr_url=QR_URL))
        ad = await ctx.ads.create(request)
        assert ad.provider == "fake_ai" and ad.prompt is not None and "Sharma Sweets" in ad.prompt.final_prompt
        assert ad.prompt.reference_image is None and ad.prompt.shot_count == 1 and "One continuous shot" in ad.prompt.final_prompt
        assert "will loop" not in ad.prompt.final_prompt and "SHOT 1" not in ad.prompt.final_prompt
        assert "20%" not in ad.prompt.final_prompt and "98765" not in ad.prompt.final_prompt  # offers and phones stay out of the scene
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed", done.error
        assert prompts.calls == 1 and len(provider.calls) == 1
        call = provider.calls[0]
        assert call.prompt == done.prompt.final_prompt and call.image_path is None  # no website picture goes to the model
        assert [s.kind for s in done.composition] == ["ai_video"]  # nothing from the website in the video
        assert done.ai_video_used and done.qr_added and seen == [QR_URL]
        assert not any(path.endswith(("/img/a.jpg", "/img/b.jpg")) for path in site.hit_paths()[-3:])
        assert close(centre(frame_at(ctx.ads.video_path(ad.ad_id), 2.5, tmp_path / "m.png")), (0, 0, 255), 60)


async def test_ai_clip_loops_to_the_chosen_length(tmp_path):
    """The model makes 5 s; a 15 s ad loops that clip three times, and the prompt asks for a seamless loop."""
    async with creative_ctx(tmp_path, video_max_seconds=5) as (ctx, provider, *_):
        request = GenerateAdRequest(business=BusinessOverrides(name="Loop Cafe", services=["cold brew", "croissants"]),
                                    options=AdOptions(duration_seconds=15), creative=auto("ai"))
        ad = await ctx.ads.create(request)
        assert ad.prompt.duration_seconds == 5 and "will loop" in ad.prompt.final_prompt
        assert "cold brew" in ad.prompt.final_prompt and "croissants" in ad.prompt.final_prompt  # the scene shows the real services
        assert any("looped to fill 15 seconds" in w for w in ad.warnings)
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed", done.error
        assert provider.calls[0].duration_seconds == 5 and len(provider.calls) == 1  # paid for ONE 5 s clip only
        assert [(s.kind, s.seconds) for s in done.composition] == [("ai_video", 15.0)]
        assert 14.5 <= (await probe_media(ctx.ads.video_path(done.ad_id))).duration <= 15.5 and done.actual_duration_seconds == 15


async def test_mixed_mode_puts_original_images_around_the_looped_ai_clip(tmp_path):
    """Mixed mode -> original opening image -> AI video (looped to the length) -> original closing image."""
    async with creative_ctx(tmp_path, provider=CountingProvider(seconds=3.0)) as (ctx, provider, prompts, _), _served(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        a, b = [u for u in job.result.images if u.endswith(("/img/a.jpg", "/img/b.jpg"))]
        request = GenerateAdRequest(job_id=job.job_id, options=AdOptions(duration_seconds=5), creative=auto("mixed", selected_image_urls=[a, b]))
        done = await finished_ad(ctx, (await ctx.ads.create(request)).ad_id)
        assert done.status == "completed", done.error
        assert [(s.kind, s.source) for s in done.composition] == [("website_image", a), ("ai_video", "fake_ai"), ("website_image", b)]
        assert done.composition[1].seconds == 5.0  # the 3 s clip is looped to the chosen 5 s
        assert provider.calls[0].image_path is not None and len(provider.calls) == 1 and prompts.calls == 1 and done.ai_video_used
        assert any("3.0-second clip" in w for w in done.warnings)
        path = ctx.ads.video_path(done.ad_id)
        info = await probe_media(path)
        assert 9.5 <= info.duration <= 10.6
        assert close(centre(frame_at(path, 1.2, tmp_path / "a.png")), (210, 90, 40))  # original a.jpg first
        assert close(centre(frame_at(path, 5.0, tmp_path / "m.png")), (0, 0, 255), 60)  # generated footage in the middle
        assert close(centre(frame_at(path, 8.8, tmp_path / "b.png")), (30, 140, 90))  # original b.jpg last


async def test_ai_provider_failure_is_labelled_fallback_or_fails_honestly(tmp_path):
    """Provider failure -> an explicitly labelled fallback (never called AI footage), or a clean failure."""
    async with creative_ctx(tmp_path, provider=CountingProvider(name="flaky_ai", fail=True)) as (ctx, provider, *_):
        done = await finished_ad(ctx, (await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Fallback Cafe"), creative=auto("ai")))).ad_id)
        assert done.status == "completed_with_fallback" and done.fallback_used and not done.ai_video_used
        assert [s.kind for s in done.composition] == ["fallback_video"]
        assert any("NOT AI-generated" in w for w in done.warnings) and "not AI footage" in done.message
        assert len(provider.calls) == 1
    async with creative_ctx(tmp_path / "strict", provider=CountingProvider(name="flaky_ai", fail=True), video_fallback_on_error=False) as (ctx, *_):
        done = await finished_ad(ctx, (await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Strict Cafe"), creative=auto("ai")))).ad_id)
        assert done.status == "failed" and done.error == "model is down" and done.video_url is None
        assert ctx.ads.video_path(done.ad_id) is None


async def test_ai_modes_are_refused_when_no_ai_provider_is_configured(tmp_path):
    """AI and mixed modes never silently produce a demo clip: without a provider they are refused up front."""
    settings = make_settings(tmp_path)  # video_provider=mock
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), start_background=False)
    try:
        scanned = ScrapeResult(status="ok", site=SiteInfo(name="X Cafe"), images=["https://x.example/a.jpg"])
        for request in (
            GenerateAdRequest(business=BusinessOverrides(name="X Cafe"), creative=auto("ai")),
            GenerateAdRequest(scrape_result=scanned, creative=auto("mixed")),
        ):
            with pytest.raises(AiVideoUnavailable):
                await ctx.ads.create(request)
        assert await ctx.db.count_since("ad", 0) == 0
        config = Api(ctx).config()
        modes = {m.id: m for m in config.creative_modes}
        assert config.ai_video_available is False and "VIDEO_MODEL_API_KEY" in config.ai_video_message
        assert modes["ai"].available is False and modes["mixed"].available is False and modes["website"].available
        assert config.compose_durations == [5, 10, 15, 20]
        error = await _api_error(Api(ctx).create_ad(GenerateAdRequest(business=BusinessOverrides(name="X"), creative=auto("ai")), "c"))
        assert (error.status, error.code) == (422, "ai_video_unavailable")
    finally:
        await ctx.close()


async def test_a_running_ad_can_be_cancelled(tmp_path):
    """Cancelling stops the work, keeps no video and says so."""
    async with creative_ctx(tmp_path, provider=CountingProvider(delay=30)) as (ctx, provider, *_):
        ad = await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Slow Cafe"), creative=auto("ai"), wait_for_prompt=False))
        for _ in range(100):
            if provider.calls:
                break
            await asyncio.sleep(0.1)
        cancelled = await Api(ctx).cancel_ad(ad.ad_id)
        assert cancelled.status == "failed" and cancelled.error == CANCELLED_MESSAGE
        assert ctx.ads.video_path(ad.ad_id) is None
        assert (await _api_error(Api(ctx).cancel_ad(ad.ad_id))).code == "ad_finished"


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize("bad", [
    "", "javascript:alert(1)", "ftp://example.com/x", "http://localhost:3000/", "https://192.168.1.10/menu", "https://user:pw@example.com",
    "https://exa mple.com", "https://intranet/", "http://shop.local/", "example.com",
])
def test_invalid_qr_urls_are_rejected(bad):
    """Invalid QR destinations are validation errors."""
    with pytest.raises(ValidationError):
        manual(["a" * 32], include_qr=True, qr_url=bad)


def test_valid_qr_url_is_kept_exactly():
    """The QR destination is stored exactly as typed (only surrounding spaces removed)."""
    assert manual(["a" * 32], include_qr=True, qr_url=f" {QR_URL}\n").qr_url == QR_URL


async def test_upload_rejects_fake_unsupported_oversized_and_too_long_videos(tmp_path):
    """Upload type, codec, size and length are checked from the bytes and ffprobe, never from the file name."""
    async with creative_ctx(tmp_path, max_video_upload_bytes=400_000, max_video_upload_seconds=3) as (ctx, *_):
        api = Api(ctx)
        cases = {
            "not a supported video": UploadedFile("photo.mp4", png()),
            "not a playable video": UploadedFile("evil.mp4", b"\x00\x00\x00\x18ftypisom<?php echo 1; ?>" + b"\x00" * 64),
            "longer than 3 seconds": UploadedFile("long.mp4", make_video(tmp_path / "long.mp4", 4.0, audio=False, size="320x240")),
            "codec 'mjpeg' is not supported": UploadedFile("mjpeg.mov", make_video(tmp_path / "mjpeg.mov", 1.0, audio=False, codec="mjpeg", size="192x144")),
        }
        for reason, item in cases.items():
            error = await _api_error(api.upload([item], "video", "c"))
            assert (error.status, error.code) == (400, "bad_video") and reason in error.message, (reason, error.message)
        big = await _api_error(api.upload([UploadedFile("big.mp4", b"\x00" * 500_000)], "video", "c"))
        assert (big.status, big.code) == (413, "file_too_large")
        ok = await api.upload([UploadedFile("ok.mp4", make_video(tmp_path / "ok.mp4", 1.0, size="320x240"))], "video", "c")
        path, media = await api.asset_file(ok.assets[0].asset_id)
        assert media == "video/mp4" and path.suffix == ".mp4"
        assert [p.suffix for p in ctx.assets.root.iterdir()] == [".mp4"]  # rejected uploads leave nothing behind


@pytest.mark.parametrize("kwargs, message", [
    (dict(creation_mode="manual", creative_mode="website", use_uploaded_media=True, media_asset_ids=["a" * 32]), "only used by auto"),
    (dict(creation_mode="manual", use_ai_video=True, use_uploaded_media=True, media_asset_ids=["a" * 32]), "never call"),
    (dict(creation_mode="manual", use_website_images=True, use_uploaded_media=True, media_asset_ids=["a" * 32]), "only your uploaded"),
    (dict(creation_mode="manual"), "at least one uploaded"),
    (dict(creation_mode="auto"), "creative_mode"),
    (dict(creation_mode="auto", creative_mode="website", use_website_images=True, use_ai_video=True), "never calls the AI"),
    (dict(creation_mode="auto", creative_mode="website"), "needs use_website_images"),
    (dict(creation_mode="auto", creative_mode="ai"), "needs use_ai_video"),
    (dict(creation_mode="auto", creative_mode="ai", use_ai_video=True, use_website_images=True), "AI-generated footage only"),
    (dict(creation_mode="auto", creative_mode="mixed", use_ai_video=True), "both"),
    (dict(creation_mode="auto", creative_mode="ai", use_ai_video=True, selected_image_urls=["https://x.example/a.jpg"]), "needs use_website_images"),
    (dict(creation_mode="auto", creative_mode="ai", use_ai_video=True, use_uploaded_media=True), "given together"),
    (dict(creation_mode="auto", creative_mode="ai", use_ai_video=True, qr_url=QR_URL), "include_qr is false"),
    (dict(creation_mode="auto", creative_mode="ai", use_ai_video=True, media_asset_ids=["../../etc/passwd"]), "ids returned"),
])
def test_contradictory_creative_combinations_are_rejected(kwargs, message):
    """Invalid mode combinations never validate."""
    with pytest.raises(ValidationError, match=message):
        CreativeConfig(**kwargs)


def test_request_level_conflicts_are_rejected():
    """Fields that contradict the creative mode are refused instead of silently ignored."""
    with pytest.raises(ValidationError, match="do not use a website scan"):
        GenerateAdRequest(job_id="a" * 32, creative=manual(["b" * 32]))
    with pytest.raises(ValidationError, match="needs a website scan"):
        GenerateAdRequest(business=BusinessOverrides(name="X"), creative=auto("website"))
    with pytest.raises(ValidationError, match="media_asset_ids"):
        GenerateAdRequest(business=BusinessOverrides(name="X"), photo_asset_ids=["b" * 32], creative=auto("ai"))
    with pytest.raises(ValidationError, match="hero is only used"):
        GenerateAdRequest(creative=manual(["b" * 32]), hero=HeroRef(source="asset", asset_id="b" * 32))
    assert GenerateAdRequest(creative=manual(["b" * 32])).business.name == ""  # a manual ad needs no business name


async def test_missing_data_unavailable_scans_and_bad_references_are_refused(tmp_path):
    """Missing business data, unusable scans, unknown images and wrong uploads fail before any work starts."""
    async with creative_ctx(tmp_path) as (ctx, provider, prompts, _):
        blocked = await _blocked_result(ctx)
        with pytest.raises(MissingBusinessName):
            await ctx.ads.create(GenerateAdRequest(scrape_result=blocked, creative=auto("ai")))
        with pytest.raises(InvalidCreative) as no_images:
            await ctx.ads.create(GenerateAdRequest(scrape_result=blocked, business=BusinessOverrides(name="Typed Name"), creative=auto("website")))
        assert no_images.value.code == "no_images"
        with pytest.raises(UnknownJob):
            await ctx.ads.create(GenerateAdRequest(job_id="f" * 32, creative=auto("website")))
        with pytest.raises(InvalidCreative) as missing:
            await ctx.ads.create(GenerateAdRequest(creative=manual(["c" * 32])))
        assert missing.value.code == "asset_not_found"
        logo = await ctx.assets.save(png((300, 100)), "logo.png", "logo")
        with pytest.raises(InvalidCreative) as logo_as_media:
            await ctx.ads.create(GenerateAdRequest(creative=manual([logo.asset_id])))
        assert logo_as_media.value.code == "bad_media"
        async with _served(sweets_with_images()) as site:
            job = await scan(ctx, site.base)
            foreign = auto("website", selected_image_urls=["https://evil.example/tracker.png"])
            error = await _api_error(Api(ctx).create_ad(GenerateAdRequest(job_id=job.job_id, creative=foreign), "c"))
            assert (error.status, error.code) == (422, "unknown_image")
        assert provider.calls == [] and prompts.calls == 0


# --------------------------------------------------------------------------- the frontend's requests and the HTTP layer


def test_frontend_request_fixtures_match_the_backend_contract():
    """The requests the frontend builder produces (frontend/lib/creative.fixtures.json) validate here, with the same meaning."""
    if not FRONTEND_FIXTURES.is_file():  # running from a backend-only copy
        return
    cases = json.loads(FRONTEND_FIXTURES.read_text(encoding="utf-8"))
    assert {case["name"] for case in cases} >= {"manual", "website", "ai", "mixed"}
    for case in cases:
        creative = GenerateAdRequest.model_validate(case["request"]).creative
        expected = case["expect"]
        assert creative is not None, case["name"]
        assert (creative.creation_mode, creative.creative_mode) == (expected["creation_mode"], expected["creative_mode"]), case["name"]
        assert creative.calls_ai_video == expected["calls_ai_video"], case["name"]
        assert (creative.include_qr, creative.qr_url) == (expected["include_qr"], expected["qr_url"]), case["name"]


def test_http_routes_validate_creative_requests_and_video_uploads(tmp_path):
    """The real FastAPI app: 422 for contradictory JSON, 400 for a fake video, config lists the modes, cancel route exists."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(make_settings(tmp_path))) as client:
        bad = client.post("/api/generate-ad", json={"creative": {"creation_mode": "auto", "creative_mode": "website", "use_ai_video": True}})
        assert bad.status_code == 422 and bad.json()["code"] == "invalid_request" and "never calls the AI" in bad.json()["detail"]
        upload = client.post("/api/uploads", data={"kind": "video"}, files={"files": ("clip.mp4", b"not a video at all", "video/mp4")})
        assert upload.status_code == 400 and upload.json()["code"] == "bad_video"
        assert [m["id"] for m in client.get("/api/config").json()["creative_modes"]] == ["manual", "website", "ai", "mixed"]
        assert client.post("/api/ads/" + "0" * 32 + "/cancel", json={}).status_code == 404


async def test_ai_scene_shows_the_real_business_and_drops_unrelated_scraped_content(tmp_path):
    """A news site whose page carried an airline ad: the scene is a newsroom; the offer, phone and 'Head Offices' stay out."""
    from app.ai.facts import FactSheet
    from app.ai.prompt_builder import PromptBuilder

    facts = FactSheet(
        name="The Guardian", category="News", description="Latest news, sport and opinion. Fly Jetstar WSI to Brisbane from $236.",
        services=["Head Offices", "World news", "Call +61 2 1234 5678"], offer="Jetstar WSI to Brisbane $236", cta="Read now",
    )
    builder = PromptBuilder(make_settings(tmp_path, video_provider="magic_hour", video_model_api_key="k"))
    prompt = await builder.build_scene(facts, AdOptions(duration_seconds=10), duration_seconds=5, loop_seconds=10)
    text = prompt.final_prompt
    assert "newsroom" in text and prompt.shot_count == 1 and len(text) <= 2000
    for leaked in ("Jetstar", "236", "Head Office", "+61", "seconds", "16:9"):
        assert leaked not in text, leaked
