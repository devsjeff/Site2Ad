"""Shared pytest setup: runs `async def` tests without extra plugins and builds scrapers wired to local fixtures."""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.scraper.safety import SafetyPolicy  # noqa: E402
from app.scraper.service import Scraper  # noqa: E402

# Production uses Firefox. Developers without Firefox installed can run the render tests with TEST_BROWSER=chromium.
TEST_BROWSER = os.environ.get("TEST_BROWSER", "firefox")
LOCAL_POLICY = SafetyPolicy(allow_private=False, allowed_ports=None, exempt_hosts=frozenset({"127.0.0.1"}))


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run coroutine test functions in a fresh event loop."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        args = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**args))
        return True
    return None


def make_settings(tmp_path: Path | None = None, **overrides) -> Settings:
    """Settings for tests: small budgets, no robots surprises, temp data dir."""
    base = dict(
        data_dir=tmp_path or Path("./data-test"),
        database_url=f"sqlite:///{(tmp_path or Path('./data-test')) / 'test.db'}",
        playwright_browser=TEST_BROWSER,
        max_scrape_seconds=40.0,
        max_phase1_seconds=12.0,
        request_timeout=4.0,
        render_timeout_seconds=10.0,
        video_provider="mock",
        video_model_api_key="",
        ai_prompt_api_key="",
    )
    base.update(overrides)
    return Settings(**base)


def make_scraper(**overrides) -> Scraper:
    """A Scraper allowed to talk to 127.0.0.1 fixtures only (everything else stays blocked)."""
    return Scraper(make_settings(**overrides), policy=LOCAL_POLICY)


@pytest.fixture
def tmp_settings(tmp_path):
    """Settings pointing at a temp data dir."""
    return make_settings(tmp_path)


def _browser_installed(name: str) -> bool:
    """True when Playwright can find an installed executable for the engine (checked once at collection)."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return os.path.exists(getattr(p, name).executable_path)
    except Exception:
        return False


BROWSER_AVAILABLE = _browser_installed(TEST_BROWSER)
needs_browser = pytest.mark.skipif(
    not BROWSER_AVAILABLE,
    reason=f"{TEST_BROWSER} is not installed. Run: python -m playwright install firefox (or set TEST_BROWSER=chromium)",
)
