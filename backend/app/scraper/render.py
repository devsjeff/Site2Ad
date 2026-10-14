"""Playwright rendering for client-side-rendered sites. Firefox by default: one browser, many contexts.

Playwright is heavy, so this module is only used when detect.score_csr() says the plain HTML is an empty shell
and the cheaper sources (embedded JSON, JSON-LD, sitemap) were not enough.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from .detect import MIN_VISIBLE_TEXT_CHARS
from .fetch import Deadline
from .safety import SafetyPolicy, UnsafeUrlError, check_url_shape, resolve_public

logger = logging.getLogger(__name__)

BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}
NAVIGATION_TIMEOUT_SECONDS = 10.0
CONTENT_WAIT_SECONDS = 5.0
SCROLL_PAUSE_MS = 500
CONTENT_READY_SCRIPT = (
    "(minChars) => !!document.querySelector('nav a, header a, footer a')"
    " || (!!document.body && document.body.innerText.trim().length > minChars)"
)
FIREFOX_PREFS = {
    "permissions.default.image": 2,
    "media.autoplay.default": 5,
    "dom.webnotifications.enabled": False,
    "geo.enabled": False,
    "dom.push.enabled": False,
}
INSTALL_HINT = "Run: python -m playwright install --with-deps firefox"


@dataclass
class RenderResult:
    """Outcome of rendering one page in the browser."""

    ok: bool
    url: str
    html: str = ""
    status_code: int = 0
    error: str = ""
    error_code: str = ""  # browser_unavailable | timeout | http_error | too_large | unsafe | failed | disabled


async def _default_playwright_factory():
    """Start Playwright's driver (imported lazily so the package stays optional)."""
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    return await async_playwright().start()


class BrowserPool:
    """One shared browser, a fresh isolated context per render, a cap on parallel pages, periodic recycling."""

    def __init__(
        self,
        settings,
        policy: Optional[SafetyPolicy] = None,
        playwright_factory: Optional[Callable[[], Awaitable[Any]]] = None,
    ):
        """No browser is started until the first render() call."""
        self.settings = settings
        self.policy = policy or SafetyPolicy.from_settings(settings)
        self._factory = playwright_factory or _default_playwright_factory
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_renders))
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None
        self._jobs_on_browser = 0
        self._active: dict[int, int] = {}
        self._retired: dict[int, Any] = {}
        self.launch_count = 0  # how many browsers were started (used by tests and metrics)
        self.render_count = 0
        self._unavailable_reason = ""

    @property
    def engine_name(self) -> str:
        """Browser engine in use (firefox unless overridden)."""
        return self.settings.playwright_browser

    async def _acquire(self) -> Any:
        """Return a live browser, launching or recycling one as needed, and count the job on it."""
        async with self._lock:
            if self._playwright is None:
                self._playwright = await self._factory()
            browser = self._browser
            stale = (
                browser is None
                or not browser.is_connected()
                or self._jobs_on_browser >= max(1, self.settings.browser_recycle_jobs)
            )
            if stale:
                if browser is not None:
                    self._retired[id(browser)] = browser
                    await self._close_if_idle(browser)
                browser = await self._launch()
                self._browser = browser
                self._jobs_on_browser = 0
            self._jobs_on_browser += 1
            self._active[id(browser)] = self._active.get(id(browser), 0) + 1
            return browser

    async def _launch(self) -> Any:
        """Launch the configured engine. Firefox is the default and the only engine used in production."""
        engine_name = self.settings.playwright_browser
        engine = getattr(self._playwright, engine_name)
        kwargs: dict[str, Any] = {"headless": self.settings.playwright_headless}
        if engine_name == "firefox":
            kwargs["firefox_user_prefs"] = FIREFOX_PREFS
        elif engine_name == "chromium":
            kwargs["args"] = ["--disable-dev-shm-usage", "--no-sandbox"]
            logger.warning("Playwright is using chromium; production should use firefox (PLAYWRIGHT_BROWSER=firefox)")
        browser = await engine.launch(**kwargs)
        self.launch_count += 1
        return browser

    async def _release(self, browser: Any) -> None:
        """Mark one job done; close the browser if it was retired and is now idle."""
        async with self._lock:
            key = id(browser)
            self._active[key] = max(0, self._active.get(key, 1) - 1)
            await self._close_if_idle(browser)

    async def _close_if_idle(self, browser: Any) -> None:
        """Close a retired browser once nothing uses it (caller holds the lock)."""
        key = id(browser)
        if key in self._retired and self._active.get(key, 0) <= 0:
            self._retired.pop(key, None)
            self._active.pop(key, None)
            try:
                await browser.close()
            except Exception:
                pass

    async def _guard(self, route: Any, host_cache: dict[str, bool]) -> None:
        """Abort images/fonts/media and anything that points at a private address; let the rest through."""
        try:
            request = route.request
            if request.resource_type in BLOCKED_RESOURCE_TYPES:
                await route.abort()
                return
            if not await self._request_is_safe(request.url, host_cache):
                await route.abort()
                return
            await route.continue_()
        except Exception:
            try:
                await route.abort()
            except Exception:
                pass

    async def _request_is_safe(self, url: str, host_cache: dict[str, bool]) -> bool:
        """SSRF check for a request made by the page, cached per host for the life of the context."""
        if url.startswith(("data:", "blob:", "about:")):
            return True
        try:
            parsed = check_url_shape(url, self.policy)
        except UnsafeUrlError:
            return False
        host = (parsed.hostname or "").lower()
        if host not in host_cache:
            try:
                await resolve_public(host, parsed.port or (443 if parsed.scheme == "https" else 80), self.policy)
                host_cache[host] = True
            except UnsafeUrlError:
                host_cache[host] = False
        return host_cache[host]

    async def render(self, url: str, deadline: Deadline) -> RenderResult:
        """Render a page and return its HTML. Never raises; failures come back as RenderResult(ok=False)."""
        if self._unavailable_reason:
            return RenderResult(False, url, error=self._unavailable_reason, error_code="browser_unavailable")
        budget = deadline.cap(self.settings.render_timeout_seconds)
        if budget < 1.0:
            return RenderResult(False, url, error="Not enough time left to render the page.", error_code="timeout")
        try:
            async with self._semaphore:
                budget = deadline.cap(self.settings.render_timeout_seconds)
                if budget < 1.0:
                    return RenderResult(False, url, error="Not enough time left to render the page.", error_code="timeout")
                return await asyncio.wait_for(self._render_page(url, Deadline(budget)), timeout=budget + 3)
        except asyncio.TimeoutError:
            return RenderResult(False, url, error="The page took too long to load in the browser.", error_code="timeout")
        except ModuleNotFoundError:
            self._unavailable_reason = "Playwright is not installed (pip install playwright)."
            return RenderResult(False, url, error=self._unavailable_reason, error_code="browser_unavailable")
        except Exception as exc:
            text = str(exc)
            if "Executable doesn't exist" in text or "playwright install" in text.lower():
                self._unavailable_reason = f"The {self.engine_name} browser is not installed. {INSTALL_HINT}"
                logger.error(self._unavailable_reason)
                return RenderResult(False, url, error=self._unavailable_reason, error_code="browser_unavailable")
            logger.warning("browser render failed for %s: %s", url, text.splitlines()[0] if text else repr(exc))
            return RenderResult(False, url, error="The page could not be rendered.", error_code="failed")

    async def _render_page(self, url: str, deadline: Deadline) -> RenderResult:
        """Open a fresh context, load the page, wait for real content, scroll, and read the HTML."""
        browser = await self._acquire()
        context = None
        host_cache: dict[str, bool] = {}
        try:
            context = await browser.new_context(
                user_agent=self.settings.user_agent,
                accept_downloads=False,
                service_workers="block",
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )

            async def handle(route: Any) -> None:
                """Route every request of this context through the guard."""
                await self._guard(route, host_cache)

            await context.route("**/*", handle)
            page = await context.new_page()
            nav_timeout = deadline.cap(NAVIGATION_TIMEOUT_SECONDS)
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=int(nav_timeout * 1000))
            except Exception as exc:
                if "Timeout" in type(exc).__name__ or "timeout" in str(exc).lower():
                    return RenderResult(False, url, error="The page took too long to load in the browser.", error_code="timeout")
                raise
            status = response.status if response is not None else 0
            if status >= 500:
                return RenderResult(False, url, status_code=status, error=f"The site answered with status {status}.", error_code="http_error")
            wait = deadline.cap(CONTENT_WAIT_SECONDS)
            if wait > 0.2:
                try:
                    await page.wait_for_function(CONTENT_READY_SCRIPT, arg=MIN_VISIBLE_TEXT_CHARS, timeout=int(wait * 1000))
                except Exception:
                    pass  # page may simply have little text; extraction decides what to do
            try:
                await page.evaluate("() => window.scrollTo(0, document.body ? document.body.scrollHeight : 0)")
                await page.wait_for_timeout(SCROLL_PAUSE_MS)
                await page.evaluate("() => window.scrollTo(0, 0)")
            except Exception:
                pass
            html = await page.content()
            if len(html.encode("utf-8", errors="ignore")) > self.settings.max_response_bytes:
                return RenderResult(False, url, error="The page is too large to scan.", error_code="too_large")
            self.render_count += 1
            return RenderResult(True, page.url, html=html, status_code=status)
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            await self._release(browser)

    async def close(self) -> None:
        """Close every browser and stop the Playwright driver."""
        async with self._lock:
            browsers = list(self._retired.values())
            if self._browser is not None:
                browsers.append(self._browser)
            for browser in browsers:
                try:
                    await browser.close()
                except Exception:
                    pass
            self._browser = None
            self._retired.clear()
            self._active.clear()
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None


_BROWSER_OK: dict[str, bool] = {}


async def browser_installed(engine: str) -> tuple[bool, str]:
    """Check (cheaply, cached once it is true) that Playwright and the engine's browser binary are installed."""
    if _BROWSER_OK.get(engine):
        return True, f"{engine} ready"
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except ImportError:
        return False, "the playwright package is not installed (pip install playwright)"
    try:
        async with async_playwright() as p:
            path = getattr(p, engine).executable_path
            if path and os.path.exists(path):
                _BROWSER_OK[engine] = True
                return True, f"{engine} ready"
    except Exception as exc:  # the driver may be missing or broken
        return False, f"playwright could not start ({type(exc).__name__})"
    return False, f"the {engine} browser is not installed. {INSTALL_HINT}"
