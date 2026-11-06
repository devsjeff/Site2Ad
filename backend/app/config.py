"""Central, environment-driven settings. Nothing else in the app reads os.environ."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Mapping

logger = logging.getLogger(__name__)

# Old env names from the first prototype keep working so existing .env files do not break.
LEGACY_ENV_ALIASES = {
    "AI_PROMPT_API_KEY": ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"),
    "AI_PROMPT_BASE_URL": ("OPENAI_BASE_URL",),
    "AI_PROMPT_MODEL": ("GEMINI_MODEL", "OPENROUTER_MODEL"),
    "VIDEO_MODEL_API_KEY": ("MAGIC_HOUR_API_KEY",),
}

PLACEHOLDER_MARKERS = ("your-key-here", "your_key_here", "changeme", "xxxx")


def _one(env: Mapping[str, str], name: str) -> str:
    """Read one variable only, with the same comment and placeholder cleaning as _get, and no legacy aliases."""
    value = env.get(name)
    if value is None:
        return ""
    return _get({name: value}, name)


def _get(env: Mapping[str, str], name: str, default: str = "") -> str:
    """Read one setting, falling back to its legacy names, and ignore obvious placeholders."""
    for key in (name, *LEGACY_ENV_ALIASES.get(name, ())):
        value = env.get(key)
        if value is not None and value.strip():
            value = re.split(r"\s+#", value.strip(), maxsplit=1)[0].strip()  # "KEY=value  # note" (docker --env-file keeps the note)
            if not value or value.startswith("#"):  # a comment captured as the value, e.g. "KEY=   # note"
                continue
            if any(marker in value.lower() for marker in PLACEHOLDER_MARKERS):
                continue
            return value
    return default


def _bool(value: str, default: bool) -> bool:
    """Parse a truthy/falsy string such as 'true', '0', 'no'."""
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str, default: int) -> int:
    """Parse an int, returning the default when empty or invalid."""
    try:
        return int(value) if value != "" else default
    except ValueError:
        logger.warning("Invalid integer %r in settings, using %s", value, default)
        return default


def _float(value: str, default: float) -> float:
    """Parse a float, returning the default when empty or invalid."""
    try:
        return float(value) if value != "" else default
    except ValueError:
        logger.warning("Invalid number %r in settings, using %s", value, default)
        return default


def _list(value: str) -> list[str]:
    """Split a comma separated string into clean items."""
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """All runtime settings. Build with Settings.from_env(); tests may construct it directly."""

    # --- app / infra
    env: str = "development"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/adsify.db"
    redis_url: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    trust_proxy_headers: bool = False  # use X-Forwarded-For for rate limiting (only behind a proxy you control)

    # --- scraper limits (SCRAPE.md sections 3, 6)
    max_scrape_seconds: float = 60.0
    max_phase1_seconds: float = 12.0
    max_response_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5
    request_timeout: float = 8.0
    max_images: int = 8
    min_image_px: int = 50
    max_crawl_pages: int = 8
    crawl_concurrency: int = 4
    phase2_mode: str = "always"  # always | auto | never
    scrape_cache_ttl_hours: float = 24.0
    blocked_cache_ttl_minutes: float = 60.0
    respect_robots: bool = True
    bot_name: str = "AdsifyBot"
    user_agent: str = "Mozilla/5.0 (compatible; AdsifyBot/1.0)"
    # Test-only switch. Disables the private-network and port checks so local fixtures can be scraped.
    unsafe_allow_private_networks: bool = False

    # --- Playwright (Firefox only by default)
    playwright_browser: str = "firefox"
    playwright_headless: bool = True
    max_concurrent_renders: int = 3
    browser_recycle_jobs: int = 100
    render_timeout_seconds: float = 12.0

    # --- AI prompt builder (Gemini generateContent, or any OpenAI-compatible gateway)
    ai_prompt_api_key: str = ""
    ai_prompt_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ai_prompt_model: str = "gemini-flash-latest"
    ai_prompt_timeout_seconds: float = 40.0
    ai_copy_model: str = ""  # model for the short on-screen copy; empty = a fast one (Gemini flash-lite) or the prompt model
    ai_copy_timeout_seconds: float = 20.0  # the copy is a bonus: never make the ad wait long for it
    gemini_api_key: str = ""
    gemini_video_model: str = "gemini-omni-1.1-flash"

    # --- ElevenLabs voices (optional; the free Microsoft voices are used when this is empty, missing or used up)
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"

    # --- video generation
    video_provider: str = "auto"  # auto | gemini | magic_hour | mock
    video_model_api_key: str = ""
    magic_hour_model: str = "ltx-2.5"
    video_resolution: str = "480p"
    video_max_seconds: int = 5
    video_timeout_seconds: float = 600.0
    video_fallback_on_error: bool = True
    hero_min_side_px: int = 400
    overlay_font_path: str = ""
    video_prompt_max_chars: int = 2000  # Magic Hour rejects longer prompts
    video_clips_per_ad: int = 1  # different AI clips (one per brief concept) before looping; each one costs credits
    video_retry_attempts: int = 2  # extra tries for transient provider errors (429, 502, 503, 504)
    video_retry_backoff_seconds: float = 5.0
    compose_resolution: str = "720p"  # FFmpeg-only ads (manual uploads, website images)

    # --- job runner / abuse protection
    max_concurrent_scrapes: int = 4
    max_concurrent_ads: int = 2
    rate_limit_per_minute: int = 20
    max_ads_per_day: int = 100
    data_retention_hours: float = 72.0
    max_upload_bytes: int = 10 * 1024 * 1024
    max_upload_files: int = 10
    max_video_upload_bytes: int = 50 * 1024 * 1024
    max_video_upload_seconds: int = 60

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, load_dotenv_file: bool = True) -> "Settings":
        """Build Settings from environment variables (and a .env file when python-dotenv is present)."""
        if env is None:
            if load_dotenv_file:
                try:
                    from dotenv import load_dotenv

                    load_dotenv()
                except ImportError:
                    pass
            env = os.environ
        g = lambda name, default="": _get(env, name, default)  # noqa: E731
        d = cls()
        # A small Render instance cannot keep Firefox open while it also encodes a video.
        if _bool(g("RENDER"), False):
            d.max_concurrent_renders = 1
            d.render_timeout_seconds = 30.0
            d.max_scrape_seconds = 120.0
            d.max_crawl_pages = 3
            d.max_concurrent_ads = 1
        gemini_api_key = _one(env, "GEMINI_API_KEY")
        explicit_base = _one(env, "AI_PROMPT_BASE_URL") or _one(env, "OPENAI_BASE_URL")
        explicit_model = _one(env, "AI_PROMPT_MODEL")
        gemini_model = _one(env, "GEMINI_MODEL")
        openrouter_key = _one(env, "OPENROUTER_API_KEY")
        openai_key = _one(env, "OPENAI_API_KEY")
        explicit_prompt = _one(env, "AI_PROMPT_API_KEY")
        prompt_key = gemini_api_key or explicit_prompt or openrouter_key or openai_key
        # A Gemini key replaces an old OpenRouter URL. An OpenRouter key with no URL keeps the OpenRouter host.
        if explicit_base and not (gemini_api_key and "openrouter.ai" in explicit_base):
            prompt_base = explicit_base.rstrip("/")
        elif gemini_api_key or not (openrouter_key or explicit_prompt or openai_key):
            prompt_base = d.ai_prompt_base_url
        elif openai_key and not openrouter_key and not explicit_prompt:
            prompt_base = "https://api.openai.com/v1"
        else:
            prompt_base = "https://openrouter.ai/api/v1"
        if gemini_api_key and gemini_model:
            prompt_model = gemini_model
        elif gemini_api_key and explicit_model in {"", "openrouter/free"}:
            prompt_model = d.ai_prompt_model
        elif explicit_model:
            prompt_model = explicit_model
        elif gemini_model:
            prompt_model = gemini_model
        elif _one(env, "OPENROUTER_MODEL"):
            prompt_model = _one(env, "OPENROUTER_MODEL")
        elif openrouter_key or explicit_prompt:
            prompt_model = "openrouter/free"
        else:
            prompt_model = d.ai_prompt_model
        return cls(
            env=g("APP_ENV", d.env),
            log_level=g("LOG_LEVEL", d.log_level).upper(),
            data_dir=Path(g("DATA_DIR", str(d.data_dir))),
            database_url=g("DATABASE_URL", d.database_url),
            redis_url=g("REDIS_URL"),
            cors_origins=_list(g("CORS_ORIGINS", ",".join(d.cors_origins))),
            trust_proxy_headers=_bool(g("TRUST_PROXY_HEADERS"), d.trust_proxy_headers),
            max_scrape_seconds=_float(g("MAX_SCRAPE_SECONDS"), d.max_scrape_seconds),
            max_phase1_seconds=_float(g("MAX_PHASE1_SECONDS"), d.max_phase1_seconds),
            max_response_bytes=_int(g("MAX_RESPONSE_BYTES"), d.max_response_bytes),
            max_redirects=_int(g("MAX_REDIRECTS"), d.max_redirects),
            request_timeout=_float(g("REQUEST_TIMEOUT_SECONDS"), d.request_timeout),
            max_images=_int(g("MAX_IMAGES"), d.max_images),
            min_image_px=_int(g("MIN_IMAGE_PX"), d.min_image_px),
            max_crawl_pages=_int(g("MAX_CRAWL_PAGES"), d.max_crawl_pages),
            crawl_concurrency=_int(g("CRAWL_CONCURRENCY"), d.crawl_concurrency),
            phase2_mode=g("PHASE2_MODE", d.phase2_mode).lower(),
            scrape_cache_ttl_hours=_float(g("SCRAPE_CACHE_TTL_HOURS"), d.scrape_cache_ttl_hours),
            blocked_cache_ttl_minutes=_float(g("BLOCKED_CACHE_TTL_MINUTES"), d.blocked_cache_ttl_minutes),
            respect_robots=_bool(g("RESPECT_ROBOTS"), d.respect_robots),
            bot_name=g("BOT_NAME", d.bot_name),
            user_agent=g("USER_AGENT", d.user_agent),
            unsafe_allow_private_networks=_bool(g("UNSAFE_ALLOW_PRIVATE_NETWORKS"), False),
            playwright_browser=g("PLAYWRIGHT_BROWSER", d.playwright_browser).lower(),
            playwright_headless=_bool(g("PLAYWRIGHT_HEADLESS"), d.playwright_headless),
            max_concurrent_renders=_int(g("MAX_CONCURRENT_RENDERS"), d.max_concurrent_renders),
            browser_recycle_jobs=_int(g("BROWSER_RECYCLE_JOBS"), d.browser_recycle_jobs),
            render_timeout_seconds=_float(g("RENDER_TIMEOUT_SECONDS"), d.render_timeout_seconds),
            ai_prompt_api_key=prompt_key,
            ai_prompt_base_url=prompt_base,
            ai_prompt_model=prompt_model,
            ai_prompt_timeout_seconds=_float(g("AI_PROMPT_TIMEOUT_SECONDS"), d.ai_prompt_timeout_seconds),
            ai_copy_model=g("AI_COPY_MODEL") or d.ai_copy_model,
            ai_copy_timeout_seconds=_float(g("AI_COPY_TIMEOUT_SECONDS"), d.ai_copy_timeout_seconds),
            gemini_api_key=gemini_api_key,
            gemini_video_model=g("GEMINI_VIDEO_MODEL", d.gemini_video_model),
            elevenlabs_api_key=g("ELEVENLABS_API_KEY"),
            elevenlabs_model=g("ELEVENLABS_MODEL", d.elevenlabs_model),
            video_provider=g("VIDEO_PROVIDER", d.video_provider).lower(),
            video_model_api_key=g("VIDEO_MODEL_API_KEY"),
            magic_hour_model=g("MAGIC_HOUR_MODEL", d.magic_hour_model),
            video_resolution=g("VIDEO_RESOLUTION", d.video_resolution),
            video_max_seconds=_int(g("VIDEO_MAX_SECONDS"), d.video_max_seconds),
            video_timeout_seconds=_float(g("VIDEO_TIMEOUT_SECONDS"), d.video_timeout_seconds),
            video_fallback_on_error=_bool(g("VIDEO_FALLBACK_ON_ERROR"), d.video_fallback_on_error),
            hero_min_side_px=_int(g("HERO_MIN_SIDE_PX"), d.hero_min_side_px),
            overlay_font_path=g("OVERLAY_FONT_PATH"),
            compose_resolution=g("COMPOSE_RESOLUTION", d.compose_resolution),
            video_prompt_max_chars=_int(g("VIDEO_PROMPT_MAX_CHARS"), d.video_prompt_max_chars),
            video_clips_per_ad=_int(g("VIDEO_CLIPS_PER_AD"), d.video_clips_per_ad),
            video_retry_attempts=_int(g("VIDEO_RETRY_ATTEMPTS"), d.video_retry_attempts),
            video_retry_backoff_seconds=_float(g("VIDEO_RETRY_BACKOFF_SECONDS"), d.video_retry_backoff_seconds),
            max_concurrent_scrapes=_int(g("MAX_CONCURRENT_SCRAPES"), d.max_concurrent_scrapes),
            max_concurrent_ads=_int(g("MAX_CONCURRENT_ADS"), d.max_concurrent_ads),
            rate_limit_per_minute=_int(g("RATE_LIMIT_PER_MINUTE"), d.rate_limit_per_minute),
            max_ads_per_day=_int(g("MAX_ADS_PER_DAY"), d.max_ads_per_day),
            data_retention_hours=_float(g("DATA_RETENTION_HOURS"), d.data_retention_hours),
            max_upload_bytes=_int(g("MAX_UPLOAD_BYTES"), d.max_upload_bytes),
            max_upload_files=_int(g("MAX_UPLOAD_FILES"), d.max_upload_files),
            max_video_upload_bytes=_int(g("MAX_VIDEO_UPLOAD_BYTES"), d.max_video_upload_bytes),
            max_video_upload_seconds=_int(g("MAX_VIDEO_UPLOAD_SECONDS"), d.max_video_upload_seconds),
        )

    # ---- derived helpers
    @property
    def gemini_key(self) -> str:
        """Key for Gemini video. An OpenRouter prompt key is never sent to Gemini."""
        return self.gemini_api_key

    @property
    def effective_video_provider(self) -> str:
        """Resolve 'auto' to Gemini when that key exists, else Magic Hour, else the offline mock provider."""
        if self.video_provider == "auto":
            if self.gemini_key:
                return "gemini"
            return "magic_hour" if self.video_model_api_key else "mock"
        return self.video_provider

    @property
    def database_path(self) -> Path:
        """File path of the SQLite database parsed from DATABASE_URL."""
        url = self.database_url
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if url.startswith(prefix):
                raw = url[len(prefix):]
                return Path(raw) if raw else self.data_dir / "adsify.db"
        raise ValueError(
            f"Unsupported DATABASE_URL {url!r}. This build ships a SQLite store (sqlite:///path/to/file.db). "
            "See README 'Scaling' for moving to Postgres."
        )

    def validate(self) -> list[str]:
        """Return human readable configuration problems (empty list means OK)."""
        problems: list[str] = []
        if self.playwright_browser not in {"firefox", "chromium", "webkit"}:
            problems.append(f"PLAYWRIGHT_BROWSER must be firefox, chromium or webkit (got {self.playwright_browser!r})")
        if self.phase2_mode not in {"always", "auto", "never"}:
            problems.append(f"PHASE2_MODE must be always, auto or never (got {self.phase2_mode!r})")
        if self.video_provider not in {"auto", "gemini", "magic_hour", "mock"}:
            problems.append(f"VIDEO_PROVIDER must be auto, gemini, magic_hour or mock (got {self.video_provider!r})")
        if self.effective_video_provider == "gemini" and not self.gemini_key:
            problems.append("VIDEO_PROVIDER=gemini needs GEMINI_API_KEY")
        if self.effective_video_provider == "magic_hour" and not self.video_model_api_key:
            problems.append("VIDEO_PROVIDER=magic_hour needs VIDEO_MODEL_API_KEY")
        if "*" in self.cors_origins and len(self.cors_origins) > 1:
            problems.append("CORS_ORIGINS mixes '*' with explicit origins")
        try:
            self.database_path
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    def public_dict(self) -> dict:
        """Settings that are safe to show to the frontend or logs (no secrets)."""
        return {
            "env": self.env,
            "video_provider": self.effective_video_provider,
            "prompt_builder": "llm" if self.ai_prompt_api_key else "template",
            "max_video_seconds": self.video_max_seconds,
            "browser": self.playwright_browser,
            "phase2_mode": self.phase2_mode,
            "redis": bool(self.redis_url),
        }


def redact(settings: Settings) -> dict:
    """Dump settings with secrets masked, for startup logging."""
    out = {}
    for f in fields(settings):
        value = getattr(settings, f.name)
        if "key" in f.name or "password" in f.name or f.name in {"redis_url"}:
            out[f.name] = "***set***" if value else ""
        else:
            out[f.name] = str(value)
    return out
