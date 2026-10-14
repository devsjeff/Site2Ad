"""Tests for settings: .env parsing, comments, placeholders, legacy names and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, _get, redact

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def test_env_example_gives_safe_demo_defaults():
    """Copying .env.example to .env must give demo mode, SQLite and no keys (comments must never become values)."""
    dotenv = pytest.importorskip("dotenv")
    values = dotenv.dotenv_values(ENV_EXAMPLE)
    assert not [k for k, v in values.items() if v and v.startswith("#")], "a comment was read as a value"
    settings = Settings.from_env(values, load_dotenv_file=False)
    assert settings.effective_video_provider == "mock"
    assert settings.video_model_api_key == "" and settings.ai_prompt_api_key == "" and settings.redis_url == ""
    assert settings.playwright_browser == "firefox"
    assert settings.validate() == []


def test_env_example_has_no_secrets():
    """The shipped example file contains no key-like values."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for needle in ("sk-or-v1", "mhk_live", "sk-proj", "Bearer "):
        assert needle not in text


def test_inline_comments_and_comment_only_values_are_ignored():
    """`docker --env-file` keeps inline notes in the value; they must not leak into settings."""
    assert _get({"A": "5   # note"}, "A") == "5"
    assert _get({"A": "# just a note"}, "A", "fallback") == "fallback"
    assert _get({"A": "abc#123"}, "A") == "abc#123"  # a # without a space before it belongs to the value


def test_placeholders_are_ignored_and_legacy_names_still_work():
    """'your-key-here' counts as unset; the old OPENROUTER_/MAGIC_HOUR_ names are honoured."""
    env = {"AI_PROMPT_API_KEY": "your-key-here", "OPENROUTER_API_KEY": "real-key-1", "MAGIC_HOUR_API_KEY": "mh-key-2"}
    settings = Settings.from_env(env, load_dotenv_file=False)
    assert settings.ai_prompt_api_key == "real-key-1"
    assert settings.video_model_api_key == "mh-key-2" and settings.effective_video_provider == "magic_hour"


def test_validation_reports_bad_values_in_plain_words():
    """Typos in enum-like settings are reported at startup instead of failing later."""
    settings = Settings.from_env({"PLAYWRIGHT_BROWSER": "netscape", "PHASE2_MODE": "sometimes", "VIDEO_PROVIDER": "dalle", "DATABASE_URL": "postgresql://x/y"}, load_dotenv_file=False)
    text = " ".join(settings.validate())
    assert "PLAYWRIGHT_BROWSER" in text and "PHASE2_MODE" in text and "VIDEO_PROVIDER" in text and "DATABASE_URL" in text


def test_bad_numbers_fall_back_to_defaults_and_redact_hides_keys():
    """A non-numeric value uses the default; secrets are masked in logs."""
    settings = Settings.from_env({"MAX_SCRAPE_SECONDS": "soon", "VIDEO_MODEL_API_KEY": "super-secret", "REDIS_URL": "redis://:pw@host/0"}, load_dotenv_file=False)
    assert settings.max_scrape_seconds == Settings().max_scrape_seconds
    dumped = str(redact(settings))
    assert "super-secret" not in dumped and "pw@host" not in dumped
