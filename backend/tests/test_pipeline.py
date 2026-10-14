"""End-to-end tests of the job layer: scan a local fixture site, build ONE prompt, make ONE (demo) video."""

from __future__ import annotations

import asyncio
import io
import time
from contextlib import asynccontextmanager

import pytest
from PIL import Image

from app.ai.facts import MissingBusinessName
from app.ai.prompt_builder import PromptBuilder
from app.context import AppContext
from app.schemas import AdOptions, BusinessOverrides, GenerateAdRequest, HeroRef, JobResponse
from app.scraper.service import Scraper
from app.services.ads import DailyLimitReached, ScanNotReady, UnknownJob
from app.video.base import VideoError, probe_video
from app.video.service import VideoService

from .conftest import LOCAL_POLICY, make_settings
from .fixture_server import FixtureServer, Route
from .sites import cloudflare_challenge, static_site


def png(size=(800, 600), color=(210, 90, 40)) -> bytes:
    """A solid colour PNG."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def sweets_with_images() -> dict:
    """The static fixture site, now with real images behind the <img> tags (hero.jpg stays 404 on purpose)."""
    routes = static_site()
    routes["/img/a.jpg"] = Route(body=png((800, 600)), content_type="image/png")
    routes["/img/b.jpg"] = Route(body=png((640, 480), (30, 140, 90)), content_type="image/png")
    routes["/static/logo.png"] = Route(body=png((240, 80), (20, 20, 120)), content_type="image/png")
    return routes


@asynccontextmanager
async def app_ctx(tmp_path, **overrides):
    """A full AppContext on a temp folder, allowed to talk to 127.0.0.1 fixtures only."""
    settings = make_settings(tmp_path, **overrides)
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), start_background=False)
    try:
        yield ctx
    finally:
        await ctx.close()


@asynccontextmanager
async def serve(routes):
    """Run a fixture website for the duration of an `async with` block."""
    with FixtureServer(routes) as site:
        yield site


async def wait_for(check, timeout: float = 60.0, interval: float = 0.1):
    """Poll an async function until it returns something truthy."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = await check()
        if value:
            return value
        await asyncio.sleep(interval)
    raise AssertionError("timed out waiting for the condition")


async def scan(ctx: AppContext, url: str, **kw) -> JobResponse:
    """Create a scrape job and wait until it is final."""
    job = await ctx.scrape_jobs.create(url, **kw)

    async def done():
        """Final snapshot or None."""
        current = await ctx.scrape_jobs.get(job.job_id)
        return current if current and current.is_final else None

    return await wait_for(done)


async def finished_ad(ctx: AppContext, ad_id: str):
    """Wait until an ad reaches a terminal status."""

    async def done():
        """Terminal snapshot or None."""
        ad = await ctx.ads.get(ad_id)
        return ad if ad and ad.status in {"completed", "completed_with_fallback", "failed"} else None

    return await wait_for(done)


# --------------------------------------------------------------------------- scrape jobs


async def test_scan_job_runs_both_phases_and_reports_progress(tmp_path):
    """Check: scan job runs both phases and reports progress."""
    async with app_ctx(tmp_path) as ctx, serve(sweets_with_images()) as site:
        first = await ctx.scrape_jobs.create(site.base)
        assert first.status in {"queued", "running"} and first.is_final is False
        seen_stages: list[str] = []
        seen_progress: list[int] = []

        async def done():
            """Record progress and return the final job."""
            job = await ctx.scrape_jobs.get(first.job_id)
            seen_stages.append(job.stage)
            seen_progress.append(job.progress)
            return job if job.is_final else None

        job = await wait_for(done)
        assert job.status == "ok" and job.result and job.result.site.name == "Sharma Sweets"
        assert job.result.site.phone == "+919876543210"
        assert job.phase2.state == "done" and job.phase2.pages_total >= 1 and job.result.pages
        assert job.progress == 100 and job.stage == "ad_ready" and job.cached is False
        assert seen_progress == sorted(seen_progress)  # progress never goes backwards
        assert set(seen_stages) <= {"queued", "fetching", "rendering", "extracting", "ad_ready"}


async def test_second_scan_of_the_same_site_comes_from_cache(tmp_path):
    """Check: second scan of the same site comes from cache."""
    async with app_ctx(tmp_path) as ctx, serve(sweets_with_images()) as site:
        first = await scan(ctx, site.base)
        hits = len(site.hit_paths())
        again = await ctx.scrape_jobs.create(site.base)
        assert again.cached is True and again.is_final and again.result.site.name == "Sharma Sweets"
        assert again.job_id != first.job_id
        assert len(site.hit_paths()) == hits  # no new request reached the website
        stored = await ctx.scrape_jobs.get(again.job_id)
        assert stored and stored.cached
        refreshed = await scan(ctx, site.base, refresh=True)
        assert refreshed.cached is False and len(site.hit_paths()) > hits


async def test_two_requests_for_one_site_share_one_job(tmp_path):
    """Check: two requests for one site share one job."""
    async with app_ctx(tmp_path) as ctx, serve(sweets_with_images()) as site:
        one, two = await asyncio.gather(ctx.scrape_jobs.create(site.base), ctx.scrape_jobs.create(site.base))
        assert one.job_id == two.job_id
        await scan(ctx, site.base)


async def test_blocked_and_invalid_sites_end_cleanly(tmp_path):
    """Check: blocked and invalid sites end cleanly."""
    async with app_ctx(tmp_path) as ctx:
        with FixtureServer(cloudflare_challenge()) as blocked_site:
            blocked = await scan(ctx, blocked_site.base)
            assert blocked.status == "blocked" and blocked.is_final and blocked.phase2.state == "skipped"
            assert "business details" in blocked.message
        for bad in ("http://localhost", "http://169.254.169.254/latest", "not a url", "ftp://example.com"):
            job = await scan(ctx, bad)
            assert job.status in {"invalid_url", "unreachable"} and job.is_final and job.result is not None


async def test_unfinished_jobs_are_closed_after_a_restart(tmp_path):
    """Check: unfinished jobs are closed after a restart."""
    settings = make_settings(tmp_path)
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), start_background=False)
    try:
        stuck = JobResponse(job_id="a" * 32, url="https://x.example", status="running", stage="fetching", progress=15)
        await ctx.db.put("job", stuck.job_id, stuck.model_dump(mode="json"), status="running")
    finally:
        await ctx.close()
    async with app_ctx(tmp_path) as ctx2:
        job = await ctx2.scrape_jobs.get("a" * 32)
        assert job.status == "internal_error" and job.is_final and "restarted" in job.message


# --------------------------------------------------------------------------- ads


async def test_full_flow_scan_prompt_video(tmp_path):
    """Check: full flow scan prompt video."""
    async with app_ctx(tmp_path) as ctx, serve(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        options = AdOptions(goal="offer", platform="instagram_reel", style="bold_pop", tone="energetic")
        ad = await ctx.ads.create(GenerateAdRequest(job_id=job.job_id, options=options))
        # wait_for_prompt: the first response already holds the ONE prompt
        assert ad.prompt is not None and ad.stage in {"prompt_ready", "generating_video", "finalizing", "completed"}
        assert ad.prompt.shot_count == 1 and ad.prompt.aspect_ratio == "9:16" and ad.prompt.final_prompt.count("NEGATIVE PROMPT:") == 1
        assert "Sharma Sweets" in ad.prompt.final_prompt and "98765" not in ad.prompt.final_prompt
        assert ad.prompt.reference_image and ad.prompt.reference_image.source == "scraped"
        assert ad.prompt.reference_image.url.endswith("/img/a.jpg")  # the og:image 404s, so the next best image is used
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed" and done.stage == "completed" and done.progress == 100 and done.fallback_used is False
        assert done.video_url == f"/api/ads/{ad.ad_id}/video" and done.provider == "mock"
        path = ctx.ads.video_path(ad.ad_id)
        assert path is not None
        info = await probe_video(path)
        assert (info.width, info.height) == (480, 854)
        assert not (ctx.ads.work_dir / ad.ad_id).exists()  # temp files are cleaned up
        stored = await ctx.db.get("ad", ad.ad_id)
        assert stored["status"] == "completed"


async def test_each_request_creates_exactly_one_ad_with_one_prompt(tmp_path):
    """Check: each request creates exactly one ad with one prompt."""
    async with app_ctx(tmp_path) as ctx, serve(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        a = await ctx.ads.create(GenerateAdRequest(job_id=job.job_id, options=AdOptions(style="minimal_modern")))
        b = await ctx.ads.create(GenerateAdRequest(job_id=job.job_id, options=AdOptions(style="nightlife_neon")))
        assert a.ad_id != b.ad_id
        assert a.prompt.final_prompt != b.prompt.final_prompt
        for ad in (a, b):
            assert ad.prompt.final_prompt.count("Create ONE") == 1
        await finished_ad(ctx, a.ad_id)
        await finished_ad(ctx, b.ad_id)


async def test_manual_business_without_any_image_still_makes_a_video(tmp_path):
    """Check: manual business without any image still makes a video."""
    async with app_ctx(tmp_path) as ctx:
        request = GenerateAdRequest(business=BusinessOverrides(name="Quiet Books", cta="Visit today"), options=AdOptions(add_overlays=True))
        ad = await ctx.ads.create(request)
        assert ad.prompt.reference_image is None and "none supplied" in ad.prompt.final_prompt
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed"
        assert any("No usable image" in w for w in done.warnings)


async def test_missing_name_unknown_job_and_unready_scan_are_rejected_up_front(tmp_path):
    """Check: missing name unknown job and unready scan are rejected up front."""
    async with app_ctx(tmp_path) as ctx:
        with pytest.raises(MissingBusinessName):
            await ctx.ads.create(GenerateAdRequest(scrape_result=(await _blocked_result(ctx))))
        with pytest.raises(UnknownJob):
            await ctx.ads.create(GenerateAdRequest(job_id="f" * 32))
        pending = JobResponse(job_id="b" * 32, url="https://x.example", status="queued")
        ctx.scrape_jobs._active[pending.job_id] = pending
        with pytest.raises(ScanNotReady):
            await ctx.ads.create(GenerateAdRequest(job_id=pending.job_id))


async def _blocked_result(ctx):
    """A scrape result of a blocked site (no facts at all)."""
    with FixtureServer(cloudflare_challenge()) as site:
        return (await scan(ctx, site.base)).result


async def test_user_details_fix_a_blocked_scan(tmp_path):
    """Check: user details fix a blocked scan."""
    async with app_ctx(tmp_path) as ctx:
        blocked = await _blocked_result(ctx)
        ad = await ctx.ads.create(GenerateAdRequest(scrape_result=blocked, business=BusinessOverrides(name="Blue Door Dental", phone="+91 99999 88888")))
        assert "Blue Door Dental" in ad.prompt.final_prompt and "99999" not in ad.prompt.final_prompt
        assert (await finished_ad(ctx, ad.ad_id)).status == "completed"


async def test_duration_is_limited_to_what_the_video_model_can_make(tmp_path):
    """Check: duration is limited to what the video model can make."""
    async with app_ctx(tmp_path, video_max_seconds=5) as ctx:
        ad = await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="X Cafe"), options=AdOptions(duration_seconds=20)))
        assert ad.prompt.duration_seconds == 5 and ad.actual_duration_seconds == 5
        assert any("up to 5 seconds" in w for w in ad.warnings)
        done = await finished_ad(ctx, ad.ad_id)
        assert done.actual_duration_seconds in {4, 5}


async def test_daily_limit(tmp_path):
    """Check: daily limit."""
    async with app_ctx(tmp_path, max_ads_per_day=1) as ctx:
        first = await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="One Cafe")))
        with pytest.raises(DailyLimitReached):
            await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Two Cafe")))
        await finished_ad(ctx, first.ad_id)


class FailingProvider:
    """A video model that is down."""

    name = "failing"

    async def generate(self, request):
        """Always fail."""
        raise VideoError("model is down")


async def test_video_model_failure_falls_back_and_is_reported(tmp_path):
    """Check: video model failure falls back and is reported."""
    settings = make_settings(tmp_path)
    video = VideoService(settings, primary=FailingProvider())
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), video=video, start_background=False)
    try:
        ad = await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Fallback Cafe")))
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "completed_with_fallback" and done.fallback_used is True
        assert any("model is down" in w for w in done.warnings)
        assert ctx.ads.video_path(ad.ad_id) is not None
    finally:
        await ctx.close()


async def test_video_model_failure_without_fallback_fails_cleanly(tmp_path):
    """Check: video model failure without fallback fails cleanly."""
    settings = make_settings(tmp_path, video_fallback_on_error=False)
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), video=VideoService(settings, primary=FailingProvider()), start_background=False)
    try:
        ad = await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Sad Cafe")))
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "failed" and done.stage == "failed" and done.error == "model is down"
        assert done.prompt is not None and done.video_url is None
    finally:
        await ctx.close()


class ExplodingPrompts(PromptBuilder):
    """A prompt builder with a bug."""

    async def build(self, *args, **kwargs):
        """Raise something unexpected."""
        raise ZeroDivisionError("secret internal detail")


async def test_unexpected_crash_fails_the_ad_without_hanging_or_leaking(tmp_path):
    """Check: unexpected crash fails the ad without hanging or leaking."""
    settings = make_settings(tmp_path)
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), prompts=ExplodingPrompts(settings), start_background=False)
    try:
        started = time.monotonic()
        ad = await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Crash Cafe")))
        assert time.monotonic() - started < 10  # wait_for_prompt returned because the ad ended
        done = await finished_ad(ctx, ad.ad_id)
        assert done.status == "failed" and "secret" not in (done.error or "") and "Something went wrong" in done.error
    finally:
        await ctx.close()


# --------------------------------------------------------------------------- uploads and hero choice


async def test_uploaded_photo_and_logo_are_used(tmp_path):
    """Check: uploaded photo and logo are used."""
    async with app_ctx(tmp_path) as ctx:
        photo = await ctx.assets.save(png((1200, 800), (10, 160, 200)), "../../etc/passwd.png", "photo")
        logo = await ctx.assets.save(png((300, 100), (200, 20, 20)), "logo.png", "logo")
        assert photo.filename == "passwd.png" and photo.url == f"/api/assets/{photo.asset_id}"
        found = await ctx.assets.find(photo.asset_id)
        assert found and found[1].suffix == ".jpg" and found[1].parent == ctx.assets.root
        assert await ctx.assets.find("../../etc/passwd") is None
        request = GenerateAdRequest(
            business=BusinessOverrides(name="Photo Cafe"), photo_asset_ids=[photo.asset_id], logo_asset_id=logo.asset_id,
            hero=HeroRef(source="asset", asset_id=photo.asset_id),
        )
        ad = await ctx.ads.create(request)
        assert ad.prompt.reference_image.source == "asset" and ad.prompt.reference_image.asset_id == photo.asset_id
        assert (await finished_ad(ctx, ad.ad_id)).status == "completed"


async def test_a_bad_explicit_hero_warns_and_another_image_is_used(tmp_path):
    """Check: a bad explicit hero warns and another image is used."""
    async with app_ctx(tmp_path) as ctx, serve(sweets_with_images()) as site:
        job = await scan(ctx, site.base)
        bad = HeroRef(source="scraped", url=site.base + "/robots.txt")
        ad = await ctx.ads.create(GenerateAdRequest(job_id=job.job_id, hero=bad))
        assert ad.prompt.reference_image.url.endswith("/img/a.jpg")
        done = await finished_ad(ctx, ad.ad_id)
        assert any("chosen hero image could not be used" in w for w in done.warnings)


async def test_upload_rejects_non_images_and_oversize_files(tmp_path):
    """Check: upload rejects non images and oversize files."""
    from app.video.images import ImageProblem

    async with app_ctx(tmp_path, max_upload_bytes=50_000) as ctx:
        with pytest.raises(ImageProblem):
            await ctx.assets.save(b"<html>not an image</html>", "x.png", "photo")
        with pytest.raises(ImageProblem, match="larger than"):
            await ctx.assets.save(b"x" * 60_000, "x.png", "photo")
        with pytest.raises(ImageProblem):
            await ctx.assets.save(png(), "x.png", "banner")


# --------------------------------------------------------------------------- housekeeping


async def test_retention_removes_old_records_and_files(tmp_path):
    """Check: retention removes old records and files."""
    async with app_ctx(tmp_path, data_retention_hours=1) as ctx:
        photo = await ctx.assets.save(png(), "p.png", "photo")
        ad = await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Old Cafe")))
        await finished_ad(ctx, ad.ad_id)
        video = ctx.ads.video_path(ad.ad_id)
        assert video is not None
        # age everything by two hours
        await asyncio.to_thread(ctx.db._exec, "UPDATE records SET created_at = created_at - 7200")
        counts = await ctx.maintenance.run_once()
        assert counts["ads"] == 1 and counts["assets"] == 1
        assert not video.exists() and await ctx.assets.find(photo.asset_id) is None
        assert await ctx.ads.get(ad.ad_id) is None
