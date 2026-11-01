"""The AI writer for the stages: one question, one JSON answer that is checked, and a retry that tells the writer what was wrong."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from ..ai.llm import LlmClient, LlmError
from ..config import Settings
from .config import StageError

logger = logging.getLogger(__name__)

_client: Optional[LlmClient] = None


def client() -> LlmClient:
    """The configured AI writer (OpenRouter, Gemini or any OpenAI-compatible gateway; see backend/.env)."""
    global _client
    if _client is None:
        _client = LlmClient(Settings.from_env())
    if not _client.enabled:
        raise StageError("No AI writer is configured. Set AI_PROMPT_API_KEY (and AI_PROMPT_BASE_URL / AI_PROMPT_MODEL) in backend/.env.")
    return _client


def set_client(replacement: Optional[LlmClient]) -> None:
    """Swap the AI writer (used by tests)."""
    global _client
    _client = replacement


# Free OpenRouter models that answer directly. The auto-router (openrouter/free) often picks a "thinking" model that spends its whole
# token budget reasoning and returns nothing, which breaks long JSON answers.
FREE_DIRECT_MODELS = ("nvidia/nemotron-3.5-lightning:free", "cohere/north-mini-code:free")


def model_candidates() -> list[str]:
    """Models to try in order: STUDIO_MODEL (env), then fast direct free models on OpenRouter, then the configured prompt model."""
    settings = client().settings
    chosen = [m for m in (os.environ.get("STUDIO_MODEL", "").strip(),) if m]
    if "openrouter.ai" in settings.ai_prompt_base_url:
        chosen += list(FREE_DIRECT_MODELS)
    chosen.append(settings.ai_prompt_model)
    return list(dict.fromkeys(chosen))


def complete(system: str, message: str, max_tokens: int, timeout: float) -> str:
    """One answer from the first model that gives one (reasoning off, so the token budget goes to the answer)."""
    writer = client()
    reasoning = {"enabled": False} if "openrouter.ai" in writer.settings.ai_prompt_base_url else None
    errors: list[str] = []
    for round_number in range(4):  # free models rate-limit bursts of requests: wait and ask again instead of giving up
        errors = []
        for model in model_candidates():
            try:
                return asyncio.run(writer.complete(system, message, max_tokens=max_tokens, model=model, timeout=timeout, reasoning=reasoning))
            except LlmError as exc:
                errors.append(f"{model}: {exc}")
                logger.info("model %s did not answer: %s", model, exc)
        if any("daily limit" in e for e in errors) or not all("rate limited" in e for e in errors) or round_number == 3:
            break  # a daily limit does not clear by waiting a few seconds
        wait = 20 * (round_number + 1)
        print(f"  (the AI models are rate limited; waiting {wait} s)", flush=True)
        time.sleep(wait)
    raise LlmError("; ".join(errors)[:400])


def parse_json(raw: str) -> Optional[dict]:
    """The first JSON object in an answer, even inside a code fence or after some words."""
    text = re.sub(r"```(?:json)?", "", raw or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def ask_json(
    system: str, user: str, check: Callable[[dict], list[str]], *, what: str, tries: int = 3, max_tokens: int = 3500, timeout: float = 120.0,
) -> dict[str, Any]:
    """Ask for a JSON object; `check` returns the problems of an answer. A bad answer is sent back with its problems, up to `tries` times."""
    writer = client()
    feedback: list[str] = []
    previous = ""
    last_problems: list[str] = []
    for attempt in range(1, tries + 1):
        message = user
        if feedback:
            message += "\n\nYour previous answer had these problems. Fix all of them and answer again with the complete JSON object:\n"
            message += "\n".join(f"- {problem}" for problem in feedback[:10])
            message += f"\n\nPrevious answer:\n{previous[:3000]}"
        try:
            raw = complete(system, message, max_tokens, timeout)
        except LlmError as exc:
            last_problems = [str(exc)]
            logger.info("%s: attempt %d failed: %s", what, attempt, exc)
            feedback, previous = [], ""
            continue
        data = parse_json(raw)
        if data is None:
            feedback, previous = ["the answer was not one JSON object"], raw
            last_problems = feedback
            continue
        problems = check(data)
        if not problems:
            return data
        feedback, previous, last_problems = problems, raw, problems
        logger.info("%s: attempt %d had %d problem(s): %s", what, attempt, len(problems), problems[:3])
    raise StageError(f"The AI writer could not produce a valid {what} after {tries} tries: {'; '.join(last_problems[:4])}")
