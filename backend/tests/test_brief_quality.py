"""Facts provenance and relevance, the Ad Brief, duration-aware shots, provider errors and retries, final-video checks."""

from __future__ import annotations

import json
import subprocess
import types
from pathlib import Path

import pytest
from PIL import Image

from app.ai.brief import build_template_brief, parse_llm_brief
from app.ai.facts import build_fact_sheet
from app.ai.guard import check_shot_timing, shot_range, validate_llm_prompt
from app.ai.prompt_builder import PromptBuilder
from app.ai.template import build_template_prompt
from app.context import AppContext
from app.schemas import AdOptions, BusinessOverrides, CreativeConfig, GenerateAdRequest, Phone, ScrapeResult, SiteInfo
from app.scraper.service import Scraper
from app.video.base import VideoError, ffmpeg_path
from app.video.magic_hour import MagicHourProvider, classify_error
from app.video.quality import check_output
from app.video.service import VideoService

from .conftest import LOCAL_POLICY, make_settings
from .test_creative import CountingProvider
from .test_pipeline import finished_ad
from .test_prompt import FakeLlm

GUARDIAN = "https://www.theguardian.example/"


def guardian_scrape() -> ScrapeResult:
    """A news site whose page also carried an airline ad (the unrelated offer must never be advertised)."""
    return ScrapeResult(
        status="ok", final_url=GUARDIAN, home_url=GUARDIAN,
        site=SiteInfo(
            name="The Guardian", title="News, sport and opinion | The Guardian", category="News",
            description="Latest news, sport and opinion from the Guardian. Fly Jetstar WSI to Brisbane from $236.",
            services=["World news", "Jetstar Brisbane flights", "Opinion"], offer="Fly Jetstar WSI to Brisbane from $236", cta="Read now",
            phones=[Phone(number="+442033532000"), Phone(number="+442033536000")], phone="+442033532000",
        ),
    )


# --------------------------------------------------------------------------- facts: provenance, relevance, conflicts


def test_unrelated_scraped_offer_and_claims_are_dropped_with_reasons():
    """A third-party offer on the advertiser's page is not a fact about the advertiser."""
    facts = build_fact_sheet(guardian_scrape(), BusinessOverrides(), AdOptions())
    assert facts.offer == "" and "offer" not in facts.sources
    assert "Jetstar" not in facts.description and "Guardian" in facts.description
    assert facts.services == ["World news", "Opinion"]
    assert any("Jetstar" in note for note in facts.rejected)
    assert "236" not in facts.allowed_text()  # raw website text does not make a number allowed in an ad
    assert facts.cta == "Read now" and facts.sources["cta"].origin == "website" and facts.sources["cta"].url == GUARDIAN
    assert any("2 different phone numbers" in note for note in facts.conflicts)


def test_user_values_override_and_are_marked_as_user_provided():
    """What the user typed wins, is kept even when it names other brands, and is labelled as user-provided."""
    business = BusinessOverrides(offer="Free Qantas lounge pass with every subscription", phone="+61 2 0000 0000")
    facts = build_fact_sheet(guardian_scrape(), business, AdOptions())
    assert facts.offer == business.offer and facts.sources["offer"].origin == "user" and facts.sources["offer"].url == ""
    assert facts.phone == "+61 2 0000 0000" and not facts.conflicts  # the user chose the number: no conflict to report
    assert facts.sources["name"].origin == "website"


def test_related_offers_are_kept():
    """A real offer about the business itself survives the relevance check."""
    scrape = guardian_scrape()
    scrape.site.offer = "Diwali offer: 20% off on gift boxes"
    scrape.site.services = ["Corporate gift boxes"]
    scrape.site.name, scrape.site.category, scrape.site.description = "Sharma Sweets", "Bakery", "Fresh mithai made daily."
    facts = build_fact_sheet(scrape, BusinessOverrides(), AdOptions())
    assert facts.offer == "Diwali offer: 20% off on gift boxes" and facts.rejected == []


# --------------------------------------------------------------------------- the Ad Brief


def test_template_brief_uses_only_facts_and_lists_what_is_missing():
    """No invented CTA or offer; missing facts are listed; every supporting fact says where it came from."""
    scrape = guardian_scrape()
    scrape.site.cta = ""
    facts = build_fact_sheet(scrape, BusinessOverrides(), AdOptions(duration_seconds=10))
    brief = build_template_brief(facts, AdOptions(duration_seconds=10), duration_seconds=10, include_qr=True)
    assert brief.cta == "" and "a call to action" in brief.missing and "an offer" in brief.missing
    assert len(brief.concepts) == 3 and len({c.title for c in brief.concepts}) == 3 and brief.chosen_concept == 0
    assert "newsroom" in brief.concept.visual and brief.builder == "template"
    assert all(fact.origin == "website" and fact.url == GUARDIAN for fact in brief.supporting_facts)
    assert brief.overlay_text == ["The Guardian"] and brief.brand_assets == ["logo", "QR code"]
    assert any("Jetstar" in note for note in brief.rejected_claims)
    assert "Jetstar" not in json.dumps(brief.model_dump()["concepts"]) and "236" not in brief.main_message


async def test_ai_brief_is_used_when_valid_and_never_adds_facts():
    """A good AI brief shapes the idea; CTA and overlays still come from the facts."""
    facts = build_fact_sheet(guardian_scrape(), BusinessOverrides(), AdOptions())
    answer = json.dumps({
        "product_focus": "independent journalism", "audience": "", "main_message": "Stay informed with the Guardian.",
        "hook": "A city waking up to the news", "cta": "Subscribe for $1",
        "concepts": [
            {"title": "Morning commute", "visual": "A commuter on a calm morning train reads the news on a tablet with a clean, generic layout, soft daylight through the window, slow push-in."},
            {"title": "Newsroom", "visual": "Journalists in a bright newsroom discuss a breaking story around a large screen of abstract graphics, camera gliding past the desks."},
        ],
    })
    builder = PromptBuilder(make_settings(), FakeLlm(answer))
    brief, notes = await builder.build_brief(facts, AdOptions(), duration_seconds=5)
    assert brief.builder == "llm" and [c.title for c in brief.concepts] == ["Morning commute", "Newsroom"] and notes == []
    assert brief.cta == "Read now" and "$1" not in json.dumps(brief.model_dump())  # the AI cannot add a CTA or a price
    prompt = await builder.build_scene(facts, AdOptions(), duration_seconds=5, brief=brief)
    assert "commuter" in prompt.final_prompt and prompt.builder == "llm"


@pytest.mark.parametrize("answer", [
    "Sure! Here is a brief: the ad shows news.",
    '{"concepts": []}',
    '{"concepts": [{"title": "x", "visual": "too short"}]}',
    json.dumps({"concepts": [{"title": "Flights", "visual": "Fly Jetstar from WSI to Brisbane for only $236, a plane taking off at sunrise over the bay."}]}),
])
async def test_malformed_or_unsafe_ai_briefs_fall_back_to_the_built_in_brief(answer):
    """Malformed JSON, empty concepts and concepts that advertise another company all fall back safely."""
    facts = build_fact_sheet(guardian_scrape(), BusinessOverrides(), AdOptions())
    builder = PromptBuilder(make_settings(), FakeLlm(answer))
    brief, notes = await builder.build_brief(facts, AdOptions(), duration_seconds=5)
    assert brief.builder == "template" and notes
    prompt = await builder.build_scene(facts, AdOptions(), duration_seconds=5, brief=brief)
    for leaked in ("Jetstar", "Brisbane", "236"):
        assert leaked not in prompt.final_prompt


def test_parse_llm_brief_accepts_fenced_json_only_when_valid():
    """Code fences around JSON are tolerated; wrong shapes are not."""
    good = '```json\n{"concepts": [{"title": "Desk", "visual": "' + "A reporter types at a sunlit desk, coffee steaming, slow push-in. " + '"}]}\n```'
    assert parse_llm_brief(good) is not None
    assert parse_llm_brief("not json") is None and parse_llm_brief('{"concepts": "nope"}') is None


async def test_end_to_end_ai_ad_never_advertises_the_unrelated_offer(tmp_path):
    """The whole AI pipeline on a page with a third-party offer: not in the prompt, the brief concepts or the overlays."""
    settings = make_settings(tmp_path)
    provider = CountingProvider()
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), video=VideoService(settings, primary=provider), start_background=False)
    try:
        creative = CreativeConfig(creation_mode="auto", creative_mode="ai", use_ai_video=True)
        done = await finished_ad(ctx, (await ctx.ads.create(GenerateAdRequest(scrape_result=guardian_scrape(), creative=creative))).ad_id)
        assert done.status == "completed", done.error
        assert done.brief is not None and done.brief.cta == "Read now"
        sent = provider.calls[0].prompt
        for leaked in ("Jetstar", "Brisbane", "236"):
            assert leaked not in sent and leaked not in done.prompt.final_prompt and leaked not in " ".join(done.brief.overlay_text)
        assert any("Jetstar" in w for w in done.warnings)  # the user is told what was left out and why
    finally:
        await ctx.close()


# --------------------------------------------------------------------------- duration-aware shots


@pytest.mark.parametrize("duration, expected", [(5, (1, 1)), (10, (1, 2)), (15, (2, 4)), (20, (2, 4))])
def test_shot_range_follows_duration(duration, expected):
    """5 s: one continuous shot; 10 s: one or two; 15-20 s: two to four."""
    assert shot_range(duration) == expected


@pytest.mark.parametrize("duration", [5, 10, 15, 20])
def test_template_prompts_are_valid_for_every_supported_duration(duration):
    """The built-in writer produces a valid prompt (count and timing) for each length the UI offers."""
    facts = build_fact_sheet(guardian_scrape(), BusinessOverrides(), AdOptions())
    options = AdOptions(duration_seconds=duration)
    text = build_template_prompt(facts, options, has_reference=False, duration_seconds=duration)
    assert check_shot_timing(text, duration) == []
    assert validate_llm_prompt(text, facts, options.aspect_ratio, duration, False).ok


def _shots(*windows: tuple[float, float]) -> str:
    """Shot lines with the given (start, end) windows."""
    return "\n".join(f"SHOT {i + 1} ({a:g}-{b:g}s): Camera: wide; Motion: slow; Lighting: soft; Action: x." for i, (a, b) in enumerate(windows))


@pytest.mark.parametrize("text, duration, problem", [
    (_shots((0, 2), (2, 4), (4, 5)), 5, "needs 1-1 shot"),  # three cuts in five seconds
    (_shots((0, 20)), 20, "needs 2-4 shot"),  # one shot cannot carry 20 seconds
    (_shots((0, 4), (4, 8)), 10, "add up to 8"),  # totals must match the duration
    (_shots((0, 4), (5, 10)), 10, "without gaps"),  # gaps are not allowed
    (_shots((0, 1), (1, 10)), 10, "too short"),  # a one-second shot is an abrupt cut
    ("SHOT 1: Camera: wide; Motion: slow; Lighting: soft; Action: x.", 5, "time range"),
])
def test_invalid_shot_counts_and_timings_are_rejected(text, duration, problem):
    """Wrong shot counts, totals, gaps and too-short shots are reported."""
    problems = check_shot_timing(text, duration)
    assert any(problem in p for p in problems), problems


def test_valid_multi_shot_timing_passes():
    """Two shots that fill ten seconds are fine."""
    assert check_shot_timing(_shots((0, 5), (5, 10)), 10) == []


# --------------------------------------------------------------------------- provider errors, retries, fallback


class ApiError(Exception):
    """Shaped like the Magic Hour SDK error."""

    def __init__(self, status: int, message: str):
        """Keep the status like the SDK does."""
        super().__init__(f"status_code: {status}, body: {{'code': 'x', 'message': '{message}'}}")
        self.status_code = status


@pytest.mark.parametrize("status, kind, retryable", [
    (401, "auth", False), (403, "auth", False), (402, "credits", False), (400, "request", False),
    (429, "rate_limited", True), (503, "server", True), (500, "server", False),
])
def test_provider_errors_are_classified(status, kind, retryable):
    """Each HTTP failure gets a kind, a retry decision and a message without the key."""
    error = classify_error(ApiError(status, "boom secret-key-123"), "secret-key-123")
    assert (error.kind, error.retryable, error.status) == (kind, retryable, status)
    assert "secret-key-123" not in str(error)


def fake_client(*outcomes):
    """A Magic Hour SDK stand-in: each call raises or returns the next outcome."""
    calls: list[dict] = []

    class Client:
        """Fake client."""

        def __init__(self, token):
            """Both endpoints share the outcome list."""
            generate = lambda **kw: self._next(kw)  # noqa: E731
            self.v1 = types.SimpleNamespace(text_to_video=types.SimpleNamespace(generate=generate), image_to_video=types.SimpleNamespace(generate=generate))

        def _next(self, kw):
            """Raise or return the next outcome."""
            calls.append(kw)
            outcome = outcomes[min(len(calls), len(outcomes)) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            target = Path(kw["download_directory"]) / "result.mp4"
            target.write_bytes(b"fake-mp4")
            return types.SimpleNamespace(status="complete", downloaded_paths=[str(target)], credits_charged=10)

    return Client, calls


def _request(tmp_path):
    """A text-to-video request."""
    from .test_video import make_request

    return make_request(tmp_path, None, duration_seconds=5)


async def test_transient_errors_are_retried_with_a_limit(tmp_path):
    """429 twice, then success: three calls. Always 503: gives up after the configured retries."""
    settings = make_settings(tmp_path, video_provider="magic_hour", video_model_api_key="k", video_retry_attempts=2, video_retry_backoff_seconds=0)
    client, calls = fake_client(ApiError(429, "slow down"), ApiError(429, "slow down"), "ok")
    result = await MagicHourProvider(settings, client).generate(_request(tmp_path))
    assert result.provider == "magic_hour" and len(calls) == 3
    client, calls = fake_client(ApiError(503, "down"))
    with pytest.raises(VideoError) as info:
        await MagicHourProvider(settings, client).generate(_request(tmp_path))
    assert info.value.kind == "server" and len(calls) == 3


async def test_authentication_failures_are_not_retried(tmp_path):
    """A 401 is reported at once with what to do; it is never retried."""
    settings = make_settings(tmp_path, video_provider="magic_hour", video_model_api_key="k", video_retry_attempts=5, video_retry_backoff_seconds=0)
    client, calls = fake_client(ApiError(401, "Unauthorized"))
    with pytest.raises(VideoError) as info:
        await MagicHourProvider(settings, client).generate(_request(tmp_path))
    assert info.value.kind == "auth" and len(calls) == 1 and "VIDEO_MODEL_API_KEY" in str(info.value)


class AuthFailingProvider:
    """A provider whose key was revoked."""

    name = "magic_hour"

    def __init__(self):
        """Count calls."""
        self.calls = 0

    async def generate(self, request):
        """Always 401."""
        self.calls += 1
        raise VideoError("Magic Hour rejected the API key (HTTP 401). Create a new key.", kind="auth", status=401)


async def test_auth_failure_fails_the_ad_clearly_instead_of_a_fake_success(tmp_path):
    """No demo clip is passed off for a bad key: the ad fails with the actionable reason and keeps provider_error."""
    settings = make_settings(tmp_path)
    provider = AuthFailingProvider()
    ctx = await AppContext.create(settings, scraper=Scraper(settings, policy=LOCAL_POLICY), video=VideoService(settings, primary=provider), start_background=False)
    try:
        creative = CreativeConfig(creation_mode="auto", creative_mode="ai", use_ai_video=True)
        done = await finished_ad(ctx, (await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Key Cafe"), creative=creative))).ad_id)
        assert done.status == "failed" and "HTTP 401" in done.error and "HTTP 401" in (done.provider_error or "")
        assert done.video_url is None and done.ai_video_used is False and provider.calls == 1
    finally:
        await ctx.close()


async def test_transient_failure_is_an_explicit_fallback_that_keeps_the_original_error(tmp_path):
    """A provider outage produces a clearly labelled demo clip, and the real reason stays visible."""
    settings = make_settings(tmp_path)
    ctx = await AppContext.create(
        settings, scraper=Scraper(settings, policy=LOCAL_POLICY), video=VideoService(settings, primary=CountingProvider(name="flaky", fail=True)),
        start_background=False,
    )
    try:
        creative = CreativeConfig(creation_mode="auto", creative_mode="ai", use_ai_video=True)
        done = await finished_ad(ctx, (await ctx.ads.create(GenerateAdRequest(business=BusinessOverrides(name="Flaky Cafe"), creative=creative))).ad_id)
        assert done.status == "completed_with_fallback" and done.fallback_used and not done.ai_video_used
        assert done.provider_error == "model is down" and [s.kind for s in done.composition] == ["fallback_video"]
    finally:
        await ctx.close()


# --------------------------------------------------------------------------- final-video checks


async def test_output_check_rejects_missing_empty_and_non_video_files(tmp_path):
    """Missing, empty and non-video files never pass."""
    assert not (await check_output(tmp_path / "missing.mp4")).ok
    (tmp_path / "empty.mp4").write_bytes(b"")
    assert "empty" in (await check_output(tmp_path / "empty.mp4")).problems[0]
    image = tmp_path / "still.png"
    Image.new("RGB", (64, 64)).save(image)
    (tmp_path / "fake.mp4").write_bytes(b"x" * 4096)
    assert not (await check_output(tmp_path / "fake.mp4")).ok


async def test_output_check_accepts_a_real_video_and_warns_about_length(tmp_path):
    """A real 2-second MP4 passes; a planned length far from the real one is a warning, not a silent pass."""
    video = tmp_path / "ok.mp4"
    subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=24", "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    report = await check_output(video, expected_seconds=2)
    assert report.ok and report.warnings == [] and (report.width, report.height) == (320, 240)
    report = await check_output(video, expected_seconds=10)
    assert report.ok and report.warnings and "10.0 seconds were planned" in report.warnings[0]
