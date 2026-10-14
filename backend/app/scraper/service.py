"""Scraper orchestrator: two phases, one time budget, always returns a typed ScrapeResult, never raises.

Phase 1 (target 5 s, hard cap 12 s): homepage only -> enough facts to start an ad draft.
Phase 2 (background, within the 60 s total): 5-10 inner pages -> better facts for the next ad.

Cost ladder (cheapest first): plain httpx -> embedded JSON / JSON-LD -> sitemap -> headless Firefox.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Awaitable, Callable, Optional

import httpx

from ..schemas import Contacts, PageInfo, Phone, ScrapeMeta, ScrapeResult, SiteInfo
from .crawl import RobotsPolicy, fetch_sitemap_urls, select_pages
from .detect import CSR_SCORE_THRESHOLD
from .extract import Extraction, extract_page
from .fetch import Deadline, Fetcher, FetchResult
from .phones import merge_phones
from .render import BrowserPool
from .safety import (
    SafetyPolicy, UnsafeUrlError, build_http_client, check_url_is_safe, home_url_of, match_platform, normalize_input_url,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, str, Optional[ScrapeResult]], Awaitable[None]]
Phase2ProgressFn = Callable[[int, int, ScrapeResult], Awaitable[None]]

MESSAGES = {
    "ok": "Website scanned.",
    "partial": "We could read only part of your website. You can still create an ad and fill in anything that is missing.",
    "blocked": "This website blocks automated readers, so we couldn't scan it. Enter your business details instead.",
    "robots": "This website asks automated tools not to read it, so we didn't. Enter your business details instead.",
    "unreachable": "We couldn't reach this website. Check the address, or enter your business details instead.",
    "timeout": "The website took too long to respond. Try again, or enter your business details instead.",
    "internal_error": "Something went wrong while reading the website. Please try again, or enter your business details instead.",
}


@dataclass
class LoadedPage:
    """One page after fetching (and rendering, when it needed JavaScript)."""

    ok: bool
    url: str
    extraction: Optional[Extraction] = None
    rendered_with: str = "httpx"
    flags: list[str] = field(default_factory=list)
    status: str = "ok"  # result status to use when ok is False
    error: str = ""
    bot_protection: Optional[str] = None


@dataclass
class ScrapeSession:
    """State carried from phase 1 to phase 2."""

    home_url: str
    page_url: str
    extraction: Extraction
    result: ScrapeResult
    robots: RobotsPolicy
    started: float
    spa: bool = False
    rendered_urls: int = 0


@dataclass
class Phase1Outcome:
    """Phase 1 result plus the session needed to continue with phase 2 (None when phase 1 failed)."""

    result: ScrapeResult
    session: Optional[ScrapeSession] = None


# --------------------------------------------------------------------------- helpers


def merge_extractions(primary: Extraction, fallback: Extraction) -> Extraction:
    """Keep primary values; fill empty fields and extend lists from fallback (e.g. raw <head> data + rendered DOM)."""
    merged = replace(primary)
    for name in ("title", "description", "language", "name", "logo", "logo_source", "address", "category", "offer", "cta", "text_excerpt", "keywords"):
        if not getattr(merged, name) and getattr(fallback, name):
            setattr(merged, name, getattr(fallback, name))
    if not merged.favicon or merged.favicon.endswith("/favicon.ico"):
        merged.favicon = fallback.favicon if fallback.favicon and not fallback.favicon.endswith("/favicon.ico") else (merged.favicon or fallback.favicon)
    for name in ("images", "whatsapp", "emails", "social", "services", "brand_colors"):
        combined = list(getattr(merged, name))
        for item in getattr(fallback, name):
            if item not in combined:
                combined.append(item)
        setattr(merged, name, combined)
    merged.phones = merge_phones([merged.phones, fallback.phones])
    seen = {link.url for link in merged.links}
    merged.links = merged.links + [link for link in fallback.links if link.url not in seen]
    merged.has_json_ld = merged.has_json_ld or fallback.has_json_ld
    if fallback.embedded.sources and not merged.embedded.sources:
        merged.embedded = fallback.embedded
    return merged


def build_site(ex: Extraction) -> SiteInfo:
    """Convert an Extraction into the public SiteInfo shape."""
    return SiteInfo(
        name=ex.name,
        title=ex.title,
        description=ex.description,
        language=ex.language,
        logo=ex.logo,
        favicon=ex.favicon,
        phone=ex.phones[0].number if ex.phones else "",
        phones=list(ex.phones),
        address=ex.address,
        category=ex.category,
        services=list(ex.services),
        offer=ex.offer,
        cta=ex.cta,
        brand_colors=list(ex.brand_colors),
        text_excerpt=ex.text_excerpt,
    )


def derive_flags(ex: Extraction, flags: list[str]) -> list[str]:
    """Add the descriptive flags the frontend uses to ask for missing details."""
    out = list(flags)

    def add(flag: str) -> None:
        """Append once."""
        if flag not in out:
            out.append(flag)

    if not ex.logo:
        add("no_logo_found")
    elif ex.logo_source == "og_image":
        add("logo_is_og_image")
    elif ex.logo.lower().split("?")[0].endswith(".svg"):
        add("logo_is_svg")
    if not ex.phones:
        add("no_phone_found")
    else:
        add({"footer": "phone_from_footer", "header": "phone_from_header", "whatsapp_link": "phone_from_whatsapp", "body": "phone_from_body", "contact_page": "phone_from_contact_page"}.get(ex.phones[0].source, "phone_found"))
    if len(ex.phones) > 1:
        add("multiple_phones")
    if not ex.images:
        add("no_images_found")
    if not ex.description:
        add("no_description_found")
    if not ex.address:
        add("no_address_found")
    if ex.parked:
        add("parked_domain")
    return out


def _fail(status: str, message: str, url: str = "", started: Optional[float] = None, bot: Optional[str] = None, flags: Optional[list[str]] = None) -> ScrapeResult:
    """Build a result for a scrape that produced no facts."""
    took = int((time.monotonic() - started) * 1000) if started else 0
    return ScrapeResult(
        status=status, message=message, final_url=url, home_url=url,  # type: ignore[arg-type]
        meta=ScrapeMeta(bot_protection=bot, took_ms=took), flags=flags or [],
    )


# --------------------------------------------------------------------------- the scraper


class Scraper:
    """Reads a website into a ScrapeResult. Create one per process; call close() on shutdown."""

    def __init__(
        self,
        settings,
        *,
        policy: Optional[SafetyPolicy] = None,
        client: Optional[httpx.AsyncClient] = None,
        pool: Optional[BrowserPool] = None,
    ):
        """Wire the safe HTTP client, fetcher and (lazy) browser pool."""
        self.settings = settings
        self.policy = policy or SafetyPolicy.from_settings(settings)
        self._owns_client = client is None
        self.client = client or build_http_client(settings, self.policy)
        self.fetcher = Fetcher(self.client, settings, self.policy)
        self.pool = pool or BrowserPool(settings, self.policy)

    async def close(self) -> None:
        """Release HTTP connections and the browser."""
        if self._owns_client:
            await self.client.aclose()
        await self.pool.close()

    # ------------------------------------------------------------------ page loading

    async def _extract(self, html: str, url: str, home_url: str, fr: Optional[FetchResult], **kw) -> Extraction:
        """Run the CPU-heavy parsing in a worker thread so the event loop stays responsive."""
        return await asyncio.to_thread(
            extract_page, html, url, home_url,
            max_images=self.settings.max_images, min_image_px=self.settings.min_image_px,
            status=fr.status_code if fr else 200, headers=fr.headers if fr else None, **kw,
        )

    def _fetch_failure(self, fr: FetchResult) -> LoadedPage:
        """Map a failed fetch to a LoadedPage carrying the right result status."""
        from .detect import detect_bot_protection

        if fr.error_code == "unsafe":
            return LoadedPage(False, fr.url, status="invalid_url", error=fr.error)
        if fr.error_code in {"timeout", "budget"}:
            return LoadedPage(False, fr.url, status="timeout", error=MESSAGES["timeout"])
        if fr.error_code == "http_error":
            label = detect_bot_protection(fr.status_code, fr.headers, fr.html)
            if label or fr.status_code in (401, 403, 429):
                return LoadedPage(False, fr.url, status="blocked", error=MESSAGES["blocked"], bot_protection=label or f"http_{fr.status_code}")
        if fr.error_code in {"too_large", "not_html"}:
            return LoadedPage(False, fr.url, status="unreachable", error=f"{fr.error} Enter your business details instead.")
        return LoadedPage(False, fr.url, status="unreachable", error=MESSAGES["unreachable"])

    async def _load(
        self,
        url: str,
        deadline: Deadline,
        home_url: str,
        *,
        is_home: bool = False,
        excerpt_chars: int = 2500,
        phone_source: str = "",
        progress: Optional[ProgressFn] = None,
        allow_render: bool = True,
    ) -> LoadedPage:
        """Fetch with httpx; if the HTML is an empty JS shell, try embedded data, then a Firefox render."""
        flags: list[str] = []
        if is_home:
            fr, extra = await self.fetcher.get_home(url, deadline)
            flags += extra
        else:
            fr = await self.fetcher.get(url, deadline)
        if not fr.ok:
            return self._fetch_failure(fr)

        ex = await self._extract(fr.html, fr.url, home_url, fr, excerpt_chars=excerpt_chars, phone_source=phone_source)
        if ex.bot_protection:
            return LoadedPage(False, fr.url, status="blocked", error=MESSAGES["blocked"], bot_protection=ex.bot_protection)

        rendered_with = "httpx"
        if ex.csr_score >= CSR_SCORE_THRESHOLD:
            flags.append("spa_site")
            if ex.embedded.is_sufficient:
                flags.append("embedded_data")  # Next.js/Nuxt/initial-state JSON was enough: no browser needed
            elif allow_render:
                if progress:
                    await progress("rendering", "This site builds its pages with JavaScript. Opening it in a browser…", None)
                rendered = await self.pool.render(fr.url, deadline)
                if rendered.ok:
                    ex2 = await self._extract(
                        rendered.html, rendered.url, home_url, None, excerpt_chars=excerpt_chars, phone_source=phone_source
                    )
                    if ex2.bot_protection:
                        return LoadedPage(False, rendered.url, status="blocked", error=MESSAGES["blocked"], bot_protection=ex2.bot_protection)
                    ex = merge_extractions(ex2, ex)
                    rendered_with = "playwright"
                    if ex2.visible_len < 80 and not ex.embedded.is_sufficient:
                        flags.append("empty_after_render")
                else:
                    flags.append("render_failed")
                    if rendered.error_code == "timeout":
                        flags.append("render_timeout")
                    if rendered.error_code == "browser_unavailable":
                        flags.append("browser_unavailable")
                    logger.info("render failed for %s: %s", fr.url, rendered.error)
            else:
                flags.append("render_skipped")
        return LoadedPage(True, fr.url, ex, rendered_with, flags)

    # ------------------------------------------------------------------ phase 1

    async def scrape_phase1(self, raw_url: str, deadline: Optional[Deadline] = None, progress: Optional[ProgressFn] = None) -> Phase1Outcome:
        """Read the homepage. Hard-capped by `deadline` (default MAX_PHASE1_SECONDS). Never raises."""
        started = time.monotonic()
        try:
            return await self._phase1(raw_url, deadline or Deadline(self.settings.max_phase1_seconds), progress, started)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("phase 1 crashed for %s", raw_url)
            return Phase1Outcome(_fail("internal_error", MESSAGES["internal_error"], started=started))

    async def _phase1(self, raw_url: str, deadline: Deadline, progress: Optional[ProgressFn], started: float) -> Phase1Outcome:
        """Phase 1 body (wrapped by scrape_phase1)."""
        async def tell(stage: str, message: str, partial: Optional[ScrapeResult] = None) -> None:
            """Report progress if a callback was given."""
            if progress:
                await progress(stage, message, partial)

        try:
            norm = normalize_input_url(raw_url, self.policy)
        except UnsafeUrlError as exc:
            return Phase1Outcome(_fail("invalid_url", exc.reason, started=started))
        platform = match_platform(norm.host)
        if platform:
            return Phase1Outcome(_fail(
                "unsupported_platform",
                f"{platform} pages can't be scanned yet. Paste your own website address, or enter your business details instead.",
                norm.home_url, started, flags=["unsupported_platform"],
            ))
        try:
            await check_url_is_safe(norm.home_url, self.policy)
        except UnsafeUrlError as exc:
            if exc.kind == "dns":
                return Phase1Outcome(_fail("unreachable", MESSAGES["unreachable"], norm.home_url, started))
            return Phase1Outcome(_fail("invalid_url", exc.reason, norm.home_url, started))

        await tell("fetching", "Reading your website…")
        robots = RobotsPolicy(self.settings.bot_name, self.settings.respect_robots)
        await robots.load(self.fetcher, norm.home_url, deadline)
        if not robots.allowed(norm.home_url):
            return Phase1Outcome(_fail("blocked", MESSAGES["robots"], norm.home_url, started, bot="robots_txt", flags=["robots_disallowed"]))

        page = await self._load(norm.home_url, deadline, norm.home_url, is_home=True, excerpt_chars=2500, progress=progress)
        if not page.ok:
            return Phase1Outcome(_fail(page.status, page.error or MESSAGES["unreachable"], norm.home_url, started, bot=page.bot_protection))

        await tell("extracting", "Finding your business details…")
        ex = page.extraction
        assert ex is not None
        flags = list(page.flags)
        home_url = home_url_of(page.url)
        page_url = page.url

        # The user may have pasted an inner page (e.g. a product page): use it to fill gaps, never to replace the homepage.
        if norm.is_inner_page and (len(ex.images) < 3 or not ex.links) and not deadline.expired:
            inner = await self._load(norm.url, deadline, home_url, excerpt_chars=1500, progress=progress)
            if inner.ok and inner.extraction is not None:
                ix = inner.extraction
                ex = merge_extractions(ex, ix) if ex.images else merge_extractions(replace(ex, images=[]), ix)
                flags.append("inner_page_used")

        status = "ok"
        message = MESSAGES["ok"]
        if "render_failed" in flags or "empty_after_render" in flags:
            status, message = "partial", MESSAGES["partial"]
        if ex.parked:
            status, message = "partial", "This website looks empty or parked. You can still create an ad by entering your business details."
        if not (ex.title or ex.description or ex.images or ex.text_excerpt):
            status, message = "partial", MESSAGES["partial"]

        flags = derive_flags(ex, flags)
        result = ScrapeResult(
            status=status, message=message,  # type: ignore[arg-type]
            final_url=page_url, home_url=home_url,
            site=build_site(ex), images=list(ex.images[: self.settings.max_images]),
            contacts=Contacts(whatsapp=ex.whatsapp, emails=ex.emails, social=ex.social),
            pages=[],
            meta=ScrapeMeta(
                rendered_with=page.rendered_with,  # type: ignore[arg-type]
                bot_protection=None, csr_score=ex.csr_score, embedded_data="embedded_data" in flags,
                took_ms=int((time.monotonic() - started) * 1000), phase=1,
                browser=self.pool.engine_name if page.rendered_with == "playwright" else None,
            ),
            flags=flags,
        )
        session = ScrapeSession(home_url, page_url, ex, result, robots, started, spa="spa_site" in flags)
        await tell("ad_ready", "Ready to draft your ad.", result)
        return Phase1Outcome(result, session)

    # ------------------------------------------------------------------ phase 2

    def should_run_phase2(self, result: ScrapeResult) -> bool:
        """Apply PHASE2_MODE: always, never, or auto (only when the homepage lacks a phone or description)."""
        mode = self.settings.phase2_mode
        if mode == "never":
            return False
        if mode == "auto":
            return not (result.site.phone and result.site.description)
        return True

    async def scrape_phase2(self, session: ScrapeSession, deadline: Deadline, progress: Optional[Phase2ProgressFn] = None) -> ScrapeResult:
        """Read up to MAX_CRAWL_PAGES inner pages and merge new facts into the result. Never raises."""
        try:
            return await self._phase2(session, deadline, progress)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("phase 2 crashed for %s", session.home_url)
            session.result.flags.append("phase2_error")
            return session.result

    async def _phase2(self, session: ScrapeSession, deadline: Deadline, progress: Optional[Phase2ProgressFn]) -> ScrapeResult:
        """Phase 2 body (wrapped by scrape_phase2)."""
        result = session.result
        hints = list(session.robots.sitemaps)
        sitemap_urls = await fetch_sitemap_urls(self.fetcher, session.home_url, hints, deadline)
        candidates = select_pages(
            session.home_url, session.extraction.links, sitemap_urls, self.settings.max_crawl_pages, exclude=[session.page_url]
        )
        candidates = [c for c in candidates if session.robots.allowed(c.url)]
        total = len(candidates)
        if progress:
            await progress(0, total, result)
        if not candidates:
            result.meta.phase = 2
            result.flags.append("no_inner_pages")
            return result

        sem = asyncio.Semaphore(max(1, self.settings.crawl_concurrency))
        done = 0
        loaded: list[tuple] = []

        async def read(candidate) -> None:
            """Fetch one inner page; failures are counted, not raised."""
            nonlocal done
            async with sem:
                page = None
                if not deadline.expired:
                    page = await self._load(
                        candidate.url, deadline, session.home_url, excerpt_chars=1200,
                        phone_source="contact_page" if candidate.kind == "contact" else "", allow_render=session.spa,
                    )
                if page is not None and page.ok and page.extraction is not None:
                    loaded.append((candidate, page))
                done += 1
                if progress:
                    await progress(done, total, result)

        await asyncio.gather(*(read(c) for c in candidates))
        loaded.sort(key=lambda item: -item[0].score)

        phone_groups: list[list[Phone]] = [result.site.phones]
        for candidate, page in loaded:
            ex = page.extraction
            assert ex is not None
            result.pages.append(PageInfo(
                url=page.url, title=ex.title, description=ex.description, text_excerpt=ex.text_excerpt,
                kind=candidate.kind, rendered_with=page.rendered_with,  # type: ignore[arg-type]
            ))
            phone_groups.append(ex.phones)
            site = result.site
            site.address = site.address or ex.address
            site.offer = site.offer or ex.offer
            site.cta = site.cta or ex.cta
            site.description = site.description or ex.description
            site.category = site.category or ex.category
            for service in ex.services:
                if service.lower() not in {s.lower() for s in site.services} and len(site.services) < 8:
                    site.services.append(service)
            for field_name in ("whatsapp", "emails", "social"):
                target = getattr(result.contacts, field_name)
                for item in getattr(ex, field_name):
                    if item not in target and len(target) < 8:
                        target.append(item)
        result.site.phones = merge_phones(phone_groups)
        result.site.phone = result.site.phones[0].number if result.site.phones else ""
        if not result.site.phones:
            pass
        elif "no_phone_found" in result.flags:
            result.flags.remove("no_phone_found")
            result.flags.append({"contact_page": "phone_from_contact_page"}.get(result.site.phones[0].source, "phone_found"))
        if result.site.address and "no_address_found" in result.flags:
            result.flags.remove("no_address_found")

        ok_count = len(loaded)
        if ok_count < total:
            result.flags.append("partial_crawl" if ok_count < max(1, total // 2) or deadline.expired else "some_pages_failed")
            if ok_count < max(1, total // 2) or deadline.expired:
                result.status = "partial"
                result.message = "We could read only some pages of your website. You can still create an ad and fill in anything that is missing."
        result.meta.phase = 2
        result.meta.took_ms = int((time.monotonic() - session.started) * 1000)
        return result

    # ------------------------------------------------------------------ both phases

    async def scrape(self, raw_url: str, progress: Optional[ProgressFn] = None) -> ScrapeResult:
        """Run phase 1 then phase 2 inside MAX_SCRAPE_SECONDS. Convenience for the CLI and tests."""
        overall = Deadline(self.settings.max_scrape_seconds)
        outcome = await self.scrape_phase1(raw_url, overall.child(self.settings.max_phase1_seconds), progress)
        if outcome.session is None:
            return outcome.result
        if self.should_run_phase2(outcome.result):
            return await self.scrape_phase2(outcome.session, overall)
        return outcome.result
