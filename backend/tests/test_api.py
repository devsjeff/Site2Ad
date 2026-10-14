"""Tests for the framework-free API layer (everything the FastAPI routes call) and the Range helper."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.api.core import Api, ApiError, UploadedFile
from app.api.ranges import RangeNotSatisfiable, parse_range, read_slice
from app.schemas import AdOptions, BusinessOverrides, GenerateAdRequest, JobResponse, ScrapeRequest

from .test_pipeline import app_ctx, finished_ad, scan, serve, sweets_with_images


def png(size=(800, 600)) -> bytes:
    """A small PNG."""
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 90, 160)).save(buffer, "PNG")
    return buffer.getvalue()


async def error_of(coro) -> ApiError:
    """Await a coroutine that must raise ApiError and return it."""
    with pytest.raises(ApiError) as info:
        await coro
    return info.value


# --------------------------------------------------------------------------- scan endpoints


async def test_scan_endpoints_and_rate_limit(tmp_path):
    """Check: scan endpoints and rate limit."""
    async with app_ctx(tmp_path, rate_limit_per_minute=2) as ctx:
        api = Api(ctx)
        a = await api.start_scrape(ScrapeRequest(url="localhost"), "1.2.3.4")
        b = await api.start_scrape(ScrapeRequest(url="http://169.254.169.254"), "1.2.3.4")
        assert isinstance(a, JobResponse) and a.job_id != b.job_id
        limited = await error_of(api.start_scrape(ScrapeRequest(url="example.com"), "1.2.3.4"))
        assert (limited.status, limited.code) == (429, "rate_limited")
        other = await api.start_scrape(ScrapeRequest(url="localhost"), "5.6.7.8")  # another client is not affected
        assert other.job_id
        missing = await error_of(api.get_job("0" * 32))
        assert (missing.status, missing.code) == (404, "job_not_found")
        await scan(ctx, "http://localhost")  # let background work finish before closing


# --------------------------------------------------------------------------- uploads


async def test_upload_photos_and_logo_and_serve_them(tmp_path):
    """Check: upload photos and logo and serve them."""
    async with app_ctx(tmp_path) as ctx:
        api = Api(ctx)
        done = await api.upload([UploadedFile("a.png", png()), UploadedFile("b.png", png((640, 480)))], "photo", "c")
        assert len(done.assets) == 2 and all(a.url.startswith("/api/assets/") for a in done.assets)
        path, media = await api.asset_file(done.assets[0].asset_id)
        assert path.is_file() and media == "image/jpeg"
        logo = await api.upload([UploadedFile("logo.png", png((300, 100)))], "logo", "c")
        assert (await api.asset_file(logo.assets[0].asset_id))[1] == "image/png"
        for bad_id in ("../../etc/passwd", "z" * 32, ""):
            assert (await error_of(api.asset_file(bad_id))).status == 404


async def test_upload_validation_and_all_or_nothing(tmp_path):
    """Check: upload validation and all or nothing."""
    async with app_ctx(tmp_path, max_upload_files=2, max_upload_bytes=100_000) as ctx:
        api = Api(ctx)
        assert (await error_of(api.upload([UploadedFile("a.png", png())], "banner", "c"))).code == "bad_kind"
        assert (await error_of(api.upload([], "photo", "c"))).code == "no_files"
        assert (await error_of(api.upload([UploadedFile("a.png", png())] * 3, "photo", "c"))).code == "too_many_files"
        assert (await error_of(api.upload([UploadedFile("a.png", png()), UploadedFile("b.png", png())], "logo", "c"))).code == "too_many_files"
        big = await error_of(api.upload([UploadedFile("big.png", b"x" * 200_000)], "photo", "c"))
        assert (big.status, big.code) == (413, "file_too_large")
        bad = await error_of(api.upload([UploadedFile("good.png", png()), UploadedFile("evil.png", b"<?php echo 1; ?>")], "photo", "c"))
        assert bad.status == 400 and bad.code == "bad_image" and bad.message.startswith("evil.png:")
        assert list((ctx.assets.root).glob("*")) == []  # the first, valid file was rolled back


# --------------------------------------------------------------------------- ads


async def test_create_ad_error_mapping(tmp_path):
    """Check: create ad error mapping."""
    async with app_ctx(tmp_path, max_ads_per_day=1) as ctx:
        api = Api(ctx)
        nameless = await error_of(api.create_ad(GenerateAdRequest(scrape_result=None, business=BusinessOverrides(name="x"), options=AdOptions()).model_copy(update={"business": BusinessOverrides()}), "c"))
        assert (nameless.status, nameless.code) == (422, "business_name_required")
        unknown = await error_of(api.create_ad(GenerateAdRequest(job_id="f" * 32), "c"))
        assert (unknown.status, unknown.code) == (404, "job_not_found")
        pending = JobResponse(job_id="b" * 32, url="https://x.example", status="queued")
        ctx.scrape_jobs._active[pending.job_id] = pending
        unready = await error_of(api.create_ad(GenerateAdRequest(job_id=pending.job_id), "c"))
        assert (unready.status, unready.code) == (409, "scan_not_ready")
        ad = await api.create_ad(GenerateAdRequest(business=BusinessOverrides(name="Cap Cafe")), "c")
        capped = await error_of(api.create_ad(GenerateAdRequest(business=BusinessOverrides(name="Two Cafe")), "c"))
        assert (capped.status, capped.code) == (429, "daily_limit")
        await finished_ad(ctx, ad.ad_id)


async def test_ad_polling_and_video_download(tmp_path):
    """Check: ad polling and video download."""
    async with app_ctx(tmp_path) as ctx, serve(sweets_with_images()) as site:
        api = Api(ctx)
        job = await scan(ctx, site.base)
        ad = await api.create_ad(GenerateAdRequest(job_id=job.job_id), "c")
        assert (await error_of(api.get_ad("0" * 32))).code == "ad_not_found"
        early = await error_of(api.ad_video(ad.ad_id)) if ad.status != "completed" else None
        if early:
            assert (early.status, early.code) == (409, "video_not_ready")
        done = await finished_ad(ctx, ad.ad_id)
        path = await api.ad_video(done.ad_id)
        assert path.suffix == ".mp4" and path.stat().st_size > 1000


async def test_failed_ad_has_no_video(tmp_path):
    """Check: failed ad has no video."""
    from .test_pipeline import ExplodingPrompts
    from app.context import AppContext
    from app.scraper.service import Scraper
    from .conftest import LOCAL_POLICY, make_settings

    settings = make_settings(tmp_path)
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), prompts=ExplodingPrompts(settings), start_background=False)
    try:
        api = Api(ctx)
        ad = await api.create_ad(GenerateAdRequest(business=BusinessOverrides(name="Crash Cafe")), "c")
        done = await finished_ad(ctx, ad.ad_id)
        err = await error_of(api.ad_video(done.ad_id))
        assert (err.status, err.code) == (404, "no_video")
    finally:
        await ctx.close()


# --------------------------------------------------------------------------- meta


async def test_config_describes_the_server_without_secrets(tmp_path):
    """Check: config describes the server without secrets."""
    async with app_ctx(tmp_path, video_max_seconds=10, video_model_api_key="", ai_prompt_api_key="sk-secret") as ctx:
        config = Api(ctx).config()
        assert config.demo_mode is True and config.video_provider == "mock" and config.prompt_builder == "llm"
        assert config.durations == [5, 10]
        assert {p["id"] for p in config.platforms} == {"taxi_screen", "instagram_reel", "youtube_shorts", "facebook_feed"}
        assert next(p for p in config.platforms if p["id"] == "instagram_reel")["aspect_ratio"] == "9:16"
        assert "sk-secret" not in config.model_dump_json()
    async with app_ctx(tmp_path, video_max_seconds=3) as ctx:
        assert Api(ctx).config().durations == [3]


async def test_health_and_ready(tmp_path):
    """Check: health and ready."""
    async with app_ctx(tmp_path) as ctx:
        api = Api(ctx)
        assert api.health().status == "ok"
        ready = await api.ready()
        assert ready.database is True and ready.status == "ok" and ready.video_provider == "mock"
        assert ready.redis is None and ctx.settings.playwright_browser in ready.browser
        assert any("Demo mode" in p for p in ready.problems)


# --------------------------------------------------------------------------- ranges


def test_parse_range():
    """Check: parse range."""
    assert parse_range(None, 1000) is None
    assert parse_range("bytes=0-99", 1000) == (0, 99)
    assert parse_range("bytes=900-", 1000) == (900, 999)
    assert parse_range("bytes=-100", 1000) == (900, 999)
    assert parse_range("bytes=0-5000", 1000) == (0, 999)
    assert parse_range("bytes=-5000", 1000) == (0, 999)
    assert parse_range("bytes=0-1,5-9", 1000) is None  # several ranges: send the whole file
    assert parse_range("items=0-9", 1000) is None
    assert parse_range("bytes=-", 1000) is None
    assert parse_range("bytes=0-9", 0) is None
    for bad in ("bytes=1000-", "bytes=50-10", "bytes=-0"):
        with pytest.raises(RangeNotSatisfiable):
            parse_range(bad, 1000)


def test_read_slice(tmp_path):
    """Check: read slice."""
    path = tmp_path / "f.bin"
    path.write_bytes(bytes(range(100)))
    assert read_slice(path, 10, 14) == bytes([10, 11, 12, 13, 14])
    assert read_slice(path, 95, 99) == bytes([95, 96, 97, 98, 99])
