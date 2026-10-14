"""Scraper tests: every scenario from the brief runs against local fixture sites."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.scraper.fetch import Deadline
from app.scraper.render import BrowserPool
from app.scraper.safety import DEFAULT_POLICY
from app.scraper.service import Scraper

from . import sites
from .conftest import LOCAL_POLICY, make_scraper, make_settings, needs_browser
from .fixture_server import FixtureServer, Route, html


async def scrape(routes: dict, path: str = "/", **settings) -> tuple:
    """Run a full scrape of a fixture site; returns (result, scraper, server request paths)."""
    with FixtureServer(routes) as srv:
        scraper = make_scraper(**settings)
        try:
            result = await scraper.scrape(srv.base + path)
        finally:
            await scraper.close()
        return result, scraper, srv.hit_paths()


# ------------------------------------------------------------------ happy path


async def test_static_site_extracts_everything_without_a_browser():
    """Check: static site extracts everything without a browser."""
    result, scraper, hits = await scrape(sites.static_site())
    site = result.site
    assert result.status == "ok"
    assert site.name == "Sharma Sweets"
    assert site.description == "Fresh mithai and namkeen made daily in Bilaspur."
    assert site.language == "en-IN"
    assert site.logo.endswith("/static/logo.png")
    assert site.favicon.endswith("/apple.png")  # apple-touch-icon wins over the small icon
    assert site.phone == "+919876543210"
    sources = {p.number: p.source for p in site.phones}
    assert sources["+919876543210"] == "tel_link"
    assert sources["+917712345678"] == "contact_page"  # landline found on the contact page in phase 2
    assert "Gandhi Chowk" in site.address
    assert site.category == "Bakery"
    assert {"Wedding catering", "Corporate gift boxes"} <= set(site.services)
    assert "20% off" in site.offer
    assert site.cta == "Order Now"
    assert site.brand_colors[0] == "#c0392b"
    assert result.contacts.whatsapp == ["+919876543210"]
    assert result.contacts.emails == ["hello@sharmasweets.example"]
    assert any("instagram.com" in s for s in result.contacts.social)
    # Playwright is only for empty shells
    assert result.meta.rendered_with == "httpx"
    assert scraper.pool.launch_count == 0 and scraper.pool.render_count == 0
    assert "/robots.txt" in hits


async def test_images_are_ranked_filtered_and_not_downloaded():
    """Check: images are ranked filtered and not downloaded."""
    result, _, hits = await scrape(sites.static_site())
    names = [u.rsplit("/", 1)[-1] for u in result.images]
    assert names[0] == "hero.jpg"  # og:image first
    assert "a.jpg" in names and "b.jpg" in names
    assert "lazy-real.jpg" in names  # data-src lazy loading is understood
    assert "pixel.gif" not in names and "tiny.png" not in names  # tracking pixel and <50px icon dropped
    assert not any(p.startswith("/img/") for p in hits), "images must not be downloaded during scraping"


async def test_many_images_are_capped_deduplicated_and_junk_removed():
    """Check: many images are capped deduplicated and junk removed."""
    result, _, _ = await scrape(sites.many_images(40))
    assert len(result.images) == 8
    assert len(set(result.images)) == 8
    joined = " ".join(result.images)
    assert "pixel" not in joined and "icon-facebook" not in joined and ".svg" not in joined and "data:" not in joined
    assert result.images[0].endswith("/img/og.jpg")


async def test_important_pages_only_and_skip_list():
    """Check: important pages only and skip list."""
    result, _, hits = await scrape(sites.static_site())
    kinds = {p.kind for p in result.pages}
    assert kinds <= {"about", "services", "products", "contact", "team", "solutions", "pricing", "offers"}
    assert {"about", "contact"} <= kinds
    assert "/privacy" not in hits and "/terms" not in hits
    assert all(p.url.startswith("http://127.0.0.1") for p in result.pages)  # same domain only
    assert len(result.pages) <= 8


async def test_phase1_is_homepage_only_then_phase2_adds_pages():
    """Check: phase1 is homepage only then phase2 adds pages."""
    with FixtureServer(sites.static_site()) as srv:
        scraper = make_scraper()
        outcome = await scraper.scrape_phase1(srv.base)
        assert outcome.result.status == "ok" and outcome.result.pages == [] and outcome.result.meta.phase == 1
        assert outcome.result.site.phone == "+919876543210"
        before = set(srv.hit_paths())
        assert "/about" not in before
        final = await scraper.scrape_phase2(outcome.session, Deadline(30))
        assert final.meta.phase == 2 and len(final.pages) >= 3
        await scraper.close()


async def test_inner_page_url_scrapes_the_homepage():
    """Check: inner page url scrapes the homepage."""
    result, _, _ = await scrape(sites.static_site(), path="/about?x=1")
    assert result.home_url.endswith("/") and "about" not in result.home_url
    assert result.site.name == "Sharma Sweets"


# ------------------------------------------------------------------ empty shells and the browser


async def test_next_data_is_used_instead_of_a_browser():
    """Check: next data is used instead of a browser."""
    result, scraper, hits = await scrape(sites.next_site())
    assert result.status in {"ok", "partial"}
    assert "embedded_data" in result.flags and "spa_site" in result.flags
    assert result.meta.embedded_data is True
    assert result.site.name == "Urban Fitness Club"  # not the framework default 'Create Next App'
    assert "Nagpur" in result.site.description or "Strength" in result.site.description
    assert len(result.images) == 2
    assert scraper.pool.launch_count == 0, "a browser must not be started when embedded JSON is enough"


@needs_browser
async def test_react_shell_is_rendered_with_the_browser():
    """Check: react shell is rendered with the browser."""
    result, scraper, _ = await scrape(sites.react_shell())
    assert "spa_site" in result.flags
    assert result.meta.rendered_with == "playwright"
    assert result.meta.csr_score >= 3
    assert result.site.name == "Green Leaf Cafe"
    assert result.site.phone == "+917712345678"
    assert len(result.images) == 2
    assert scraper.pool.launch_count == 1, "one browser, many pages"
    assert result.meta.browser == make_settings().playwright_browser


async def test_missing_browser_degrades_to_partial_not_a_crash():
    """Check: missing browser degrades to partial not a crash."""
    async def broken_factory():
        """Broken factory."""
        raise ModuleNotFoundError("playwright")

    with FixtureServer(sites.react_shell()) as srv:
        scraper = Scraper(make_settings(), policy=LOCAL_POLICY, pool=BrowserPool(make_settings(), LOCAL_POLICY, playwright_factory=broken_factory))
        result = await scraper.scrape(srv.base)
        await scraper.close()
    assert result.status == "partial"
    assert "render_failed" in result.flags and "browser_unavailable" in result.flags


async def test_firefox_is_the_default_engine_and_is_what_gets_launched():
    """Check: firefox is the default engine and is what gets launched."""
    assert Settings().playwright_browser == "firefox"
    assert Settings.from_env({}, load_dotenv_file=False).playwright_browser == "firefox"
    launched: list[str] = []

    class FakeBrowser:
        def is_connected(self):
            """Is connected."""
            return True

        async def new_context(self, **kw):
            """New context."""
            raise RuntimeError("stop after launch")

        async def close(self):
            """Close."""
            pass

    class Engine:
        def __init__(self, name):
            """  init  ."""
            self.name = name

        async def launch(self, **kw):
            """Launch."""
            launched.append(self.name)
            return FakeBrowser()

    class FakePlaywright:
        firefox = Engine("firefox")

        @property
        def chromium(self):
            """Chromium."""
            raise AssertionError("chromium must never be touched")

        async def stop(self):
            """Stop."""
            pass

    async def factory():
        """Factory."""
        return FakePlaywright()

    pool = BrowserPool(Settings(), DEFAULT_POLICY, playwright_factory=factory)
    result = await pool.render("https://example.com/", Deadline(10))
    await pool.close()
    assert launched == ["firefox"]
    assert result.ok is False  # our fake context raises; the pool must report it, not crash


# ------------------------------------------------------------------ blocked, robots, errors


async def test_cloudflare_challenge_is_reported_as_blocked():
    """Check: cloudflare challenge is reported as blocked."""
    result, scraper, _ = await scrape(sites.cloudflare_challenge())
    assert result.status == "blocked"
    assert result.meta.bot_protection == "cloudflare"
    assert scraper.pool.launch_count == 0  # we never try to get around a challenge


async def test_site_merely_behind_cloudflare_is_not_blocked():
    """Check: site merely behind cloudflare is not blocked."""
    result, _, _ = await scrape(sites.cloudflare_normal())
    assert result.status != "blocked"
    assert result.site.name == "Blue Door Dental"
    assert result.meta.bot_protection is None


async def test_captcha_page_is_blocked_but_contact_form_recaptcha_is_not():
    """Check: captcha page is blocked but contact form recaptcha is not."""
    captcha = html("<html><head><title>Are you a robot?</title></head><body><div class='g-recaptcha'></div></body></html>")
    result, _, _ = await scrape({"/": captcha})
    assert result.status == "blocked" and result.meta.bot_protection == "captcha"
    long_text = "We build custom furniture for homes and offices across the city. " * 12
    form = html(f"<html><head><title>Oak Works</title></head><body><nav><a href=/a>A</a><a href=/b>B</a><a href=/c>C</a></nav><p>{long_text}</p><div class='g-recaptcha'></div></body></html>")
    result, _, _ = await scrape({"/": form})
    assert result.status != "blocked"


async def test_robots_txt_disallow_is_respected():
    """Check: robots txt disallow is respected."""
    routes = sites.static_site()
    routes["/robots.txt"] = Route(body="User-agent: *\nDisallow: /\n", content_type="text/plain")
    result, _, hits = await scrape(routes)
    assert result.status == "blocked" and result.meta.bot_protection == "robots_txt"
    assert hits == ["/robots.txt"], "the homepage must not be fetched when robots.txt forbids it"


async def test_robots_txt_can_exclude_inner_pages():
    """Check: robots txt can exclude inner pages."""
    routes = sites.static_site()
    routes["/robots.txt"] = Route(body="User-agent: *\nDisallow: /contact\nDisallow: /about\n", content_type="text/plain")
    result, _, hits = await scrape(routes)
    assert result.status == "ok"
    assert "/contact" not in hits and "/about" not in hits
    assert all("contact" not in p.url and "about" not in p.url for p in result.pages)


async def test_unreachable_status_for_http_errors_and_dead_hosts():
    """Check: unreachable status for http errors and dead hosts."""
    result, _, _ = await scrape({"/": Route(body="oops", status=500)})
    assert result.status == "unreachable"
    result, _, _ = await scrape({"/": Route(body="nope", status=404)})
    assert result.status == "unreachable"
    scraper = make_scraper()
    result = await scraper.scrape("http://127.0.0.1:9/")  # closed port
    await scraper.close()
    assert result.status == "unreachable"


# ------------------------------------------------------------------ safety


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "abc", "ftp://example.com", "file:///etc/passwd", "javascript:alert(1)", "http://user:pass@example.com",
     "http://example.com:8080/", "https://example.com/video.mp4", "https://example.com/menu.pdf", "http://exa mple.com"],
)
async def test_invalid_urls(bad):
    """Check: invalid urls."""
    scraper = Scraper(make_settings())  # production policy
    result = await scraper.scrape(bad)
    await scraper.close()
    assert result.status == "invalid_url"
    assert result.message


@pytest.mark.parametrize(
    "target",
    ["http://127.0.0.1/", "http://localhost/", "http://localhost:80/admin", "http://169.254.169.254/latest/meta-data/",
     "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.5.4/",
     "http://100.64.0.1/", "http://0.0.0.0/", "http://2130706433/", "http://0x7f.0.0.1/", "http://metadata.google.internal/",
     "http://foo.internal/", "http://printer.local/"],
)
async def test_ssrf_targets_are_blocked_before_any_connection(target):
    """Check: ssrf targets are blocked before any connection."""
    scraper = Scraper(make_settings())  # production policy: no exemptions
    result = await scraper.scrape(target)
    await scraper.close()
    assert result.status == "invalid_url", (target, result.status, result.message)
    assert result.site.name == "" and result.images == []


async def test_redirect_to_private_ip_is_blocked():
    """Check: redirect to private ip is blocked."""
    routes = {"/": Route(body="", status=302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}), "/robots.txt": Route(status=404)}
    result, scraper, _ = await scrape(routes)
    assert result.status == "invalid_url"
    assert "private" in result.message or "internal" in result.message


async def test_redirect_loop_and_chain_limits():
    """Check: redirect loop and chain limits."""
    routes = {"/": Route(status=302, headers={"Location": "/"}), "/robots.txt": Route(status=404)}
    result, _, _ = await scrape(routes)
    assert result.status == "unreachable"
    chain = {f"/r{i}": Route(status=302, headers={"Location": f"/r{i + 1}"}) for i in range(10)}
    chain["/"] = Route(status=302, headers={"Location": "/r0"})
    result, _, _ = await scrape(chain)
    assert result.status == "unreachable"


async def test_redirect_to_a_working_page_is_followed_and_final_url_reported():
    """Check: redirect to a working page is followed and final url reported."""
    routes = {"/": Route(status=301, headers={"Location": "/en/"}), "/en/": sites.minimal_site()["/"], "/robots.txt": Route(status=404)}
    result, _, _ = await scrape(routes)
    assert result.site.name == "Quiet Books"
    assert result.final_url.endswith("/en/")
    assert result.home_url.endswith("/") and not result.home_url.endswith("/en/")


async def test_large_html_and_non_html_are_rejected_safely():
    """Check: large html and non html are rejected safely."""
    big = {"/": Route(stream_bytes=6 * 1024 * 1024), "/robots.txt": Route(status=404)}
    result, _, _ = await scrape(big)
    assert result.status == "unreachable" and "large" in result.message.lower()
    video = {"/": Route(body=b"\x00\x00\x00 ftypmp42", content_type="video/mp4"), "/robots.txt": Route(status=404)}
    result, _, _ = await scrape(video)
    assert result.status == "unreachable" and "web page" in result.message.lower()
    pdf = {"/": Route(body=b"%PDF-1.4", content_type="application/pdf"), "/robots.txt": Route(status=404)}
    result, _, _ = await scrape(pdf)
    assert result.status == "unreachable"


async def test_response_size_limit_comes_from_settings():
    """Check: response size limit comes from settings."""
    routes = {"/": Route(stream_bytes=300_000), "/robots.txt": Route(status=404)}
    result, _, _ = await scrape(routes, max_response_bytes=100_000)
    assert result.status == "unreachable"


async def test_unsupported_platforms_return_a_clear_status():
    """Check: unsupported platforms return a clear status."""
    scraper = Scraper(make_settings())
    for url in ["https://www.instagram.com/mybiz/", "facebook.com/mybiz", "https://wa.me/919876543210", "https://linktr.ee/mybiz"]:
        result = await scraper.scrape(url)
        assert result.status == "unsupported_platform", url
        assert "enter your business details" in result.message
    await scraper.close()


# ------------------------------------------------------------------ time budgets, missing data, partial crawl


async def test_phase1_hard_cap_returns_timeout_instead_of_hanging():
    """Check: phase1 hard cap returns timeout instead of hanging."""
    import time

    routes = {"/": Route(body="<html><title>Slow</title></html>", delay=3.0), "/robots.txt": Route(status=404)}
    with FixtureServer(routes) as srv:
        scraper = make_scraper(request_timeout=8.0)
        started = time.monotonic()
        outcome = await scraper.scrape_phase1(srv.base, Deadline(1.0))
        elapsed = time.monotonic() - started
        await scraper.close()
    assert outcome.result.status == "timeout"
    assert elapsed < 2.5


async def test_missing_phone_address_and_logo_are_reported_not_invented():
    """Check: missing phone address and logo are reported not invented."""
    result, _, _ = await scrape(sites.minimal_site())
    assert result.site.phone == "" and result.site.phones == []
    assert result.site.address == ""
    assert result.site.logo == ""
    assert {"no_phone_found", "no_address_found", "no_logo_found", "no_images_found"} <= set(result.flags)
    assert result.contacts.emails == [] and result.contacts.whatsapp == []


async def test_partial_crawl_when_most_inner_pages_fail():
    """Check: partial crawl when most inner pages fail."""
    routes = sites.partial_crawl_site()
    routes["/about"] = Route(body="x", status=500)
    routes["/services"] = Route(body="x", status=500)
    result, _, _ = await scrape(routes)
    assert result.status == "partial"
    assert "partial_crawl" in result.flags
    assert result.pages == []
    assert result.site.name == "Metro Movers"  # homepage facts are still returned


async def test_some_failed_pages_keep_status_ok_but_are_flagged():
    """Check: some failed pages keep status ok but are flagged."""
    result, _, _ = await scrape(sites.partial_crawl_site())
    assert result.status == "ok"
    assert "some_pages_failed" in result.flags
    assert len(result.pages) == 2


async def test_crawl_stops_when_the_total_budget_is_spent():
    """Check: crawl stops when the total budget is spent."""
    routes = sites.partial_crawl_site()
    for path in ("/about", "/services", "/contact", "/pricing"):
        routes[path] = Route(body=sites.html("<html><title>Slow</title><body>slow page</body></html>").body, delay=2.5)
    with FixtureServer(routes) as srv:
        scraper = make_scraper()
        outcome = await scraper.scrape_phase1(srv.base)
        result = await scraper.scrape_phase2(outcome.session, Deadline(1.0))
        await scraper.close()
    assert result.status == "partial" and "partial_crawl" in result.flags


async def test_phase2_modes():
    """Check: phase2 modes."""
    with FixtureServer(sites.static_site()) as srv:
        for mode, expect_pages in (("never", False), ("always", True), ("auto", False)):
            scraper = make_scraper(phase2_mode=mode)
            result = await scraper.scrape(srv.base)
            await scraper.close()
            assert bool(result.pages) is expect_pages, mode  # 'auto' skips: phone + description already found on the homepage


async def test_scrape_never_raises_even_if_extraction_crashes(monkeypatch):
    """Check: scrape never raises even if extraction crashes."""
    import app.scraper.service as service

    def boom(*a, **k):
        """Boom."""
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(service, "extract_page", boom)
    result, _, _ = await scrape(sites.static_site())
    assert result.status == "internal_error"
    assert "parser exploded" not in result.message  # internals never reach the user


async def test_non_utf8_pages_decode_correctly():
    """Check: non utf8 pages decode correctly."""
    body = "<html><head><meta charset='windows-1252'><title>Café Délice</title><meta name=description content='Crêpes et café'></head><body><nav><a href=/a>a</a><a href=/b>b</a><a href=/c>c</a></nav><p>" + "Bienvenue au café. " * 20 + "</p></body></html>"
    routes = {"/": Route(body=body.encode("windows-1252"), content_type="text/html"), "/robots.txt": Route(status=404)}
    result, _, _ = await scrape(routes)
    assert result.site.title == "Café Délice"
    assert result.site.description == "Crêpes et café"
