"""PromptBuilder: facts + options -> exactly ONE AdPrompt (AI writer first, deterministic template as the safety net)."""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..config import Settings
from ..schemas import AdOptions, AdPrompt, ReferenceImage
from .facts import FactSheet
from .guard import PROMPT_MAX_CHARS, validate_llm_prompt
from .llm import SYSTEM_PROMPT, LlmClient, LlmError, build_user_message
from .template import build_template_prompt, shot_count_for

logger = logging.getLogger(__name__)

NEGATIVE_RE = re.compile(r"(?im)^\s*NEGATIVE PROMPT\s*:\s*")
SHOT_RE = re.compile(r"(?im)^\s*SHOT\s+\d+\b")
LLM_ATTEMPTS = 2


def clean_llm_text(text: str) -> str:
    """Remove markdown decoration an LLM often adds (code fences, bold markers, bullets) and chatter before the prompt."""
    text = text.strip()
    fenced = re.search(r"```[a-zA-Z]*\n(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+(?=(?:SHOT|NEGATIVE|FORMAT|BUSINESS|STYLE|AUDIO|TEXT|REFERENCE)\b)", "", text)
    start = re.search(r"(?im)^\s*Create ONE\b", text)
    if start:
        text = text[start.start():]
    return text.strip()


def split_prompt(text: str) -> tuple[str, str]:
    """Split a full prompt into (positive, negative) at the 'NEGATIVE PROMPT:' line."""
    parts = NEGATIVE_RE.split(text, maxsplit=1)
    positive = parts[0].strip()
    negative = parts[1].strip() if len(parts) > 1 else ""
    return positive, negative


def count_shots(text: str) -> int:
    """Number of SHOT lines in a prompt."""
    return len(SHOT_RE.findall(text))


class PromptBuilder:
    """Builds the single prompt for one ad. Never raises for model problems: it falls back to the template."""

    def __init__(self, settings: Settings, llm: Optional[LlmClient] = None):
        """Create the builder; pass `llm` to inject a fake in tests."""
        self.settings = settings
        self.llm = llm or LlmClient(settings)

    @property
    def mode(self) -> str:
        """'llm' when an AI writer key is set, otherwise 'template'."""
        return "llm" if self.llm.enabled else "template"

    async def build(
        self, facts: FactSheet, options: AdOptions, *, reference: Optional[ReferenceImage] = None, duration_seconds: Optional[int] = None,
        loop_seconds: int = 0,
    ) -> AdPrompt:
        """Return ONE AdPrompt. `duration_seconds` is the real video length (it may be shorter than options.duration_seconds)."""
        duration = int(duration_seconds or options.duration_seconds)
        shots = shot_count_for(duration)
        has_reference = reference is not None
        warnings: list[str] = []
        text: Optional[str] = None
        model = ""

        if self.llm.enabled:
            text, warnings = await self._ask_llm(facts, options, duration, shots, has_reference, loop_seconds)
            model = self.llm.model if text else ""
        if text is None:
            text = build_template_prompt(facts, options, has_reference=has_reference, duration_seconds=duration, loop_seconds=loop_seconds)
            check = validate_llm_prompt(text, facts, options.aspect_ratio, duration, has_reference)
            if not check.ok:  # the template should always pass; if website text broke a rule, say so instead of hiding it
                warnings.extend(f"template: {problem}" for problem in check.problems[:5])
        builder = "llm" if model else "template"

        positive, negative = split_prompt(text)
        final = f"{positive}\n\nNEGATIVE PROMPT: {negative}".strip()
        if len(final) > PROMPT_MAX_CHARS:
            warnings.append("The prompt is long; some video models may shorten it.")
        return AdPrompt(
            final_prompt=final,
            positive_prompt=positive,
            negative_prompt=negative,
            platform=options.platform,
            duration_seconds=duration,
            aspect_ratio=options.aspect_ratio,
            shot_count=count_shots(final),
            builder=builder,
            model=model,
            reference_image=reference,
            warnings=warnings,
        )

    async def _ask_llm(
        self, facts: FactSheet, options: AdOptions, duration: int, shots: int, has_reference: bool, loop_seconds: int = 0,
    ) -> tuple[Optional[str], list[str]]:
        """Ask the AI writer up to LLM_ATTEMPTS times, feeding validation problems back. Returns (text or None, warnings)."""
        warnings: list[str] = []
        feedback: Optional[list[str]] = None
        previous = ""
        for attempt in range(1, LLM_ATTEMPTS + 1):
            user = build_user_message(
                facts, options, duration_seconds=duration, shots=shots, has_reference=has_reference, feedback=feedback, previous=previous,
                loop_seconds=loop_seconds,
            )
            try:
                raw = await self.llm.complete(SYSTEM_PROMPT, user)
            except LlmError as exc:
                logger.warning("AI writer failed (attempt %s): %s", attempt, exc)
                warnings.append(f"{exc} Used the built-in prompt writer instead.")
                return None, warnings
            except Exception as exc:  # defensive: any unexpected client error must not fail the ad
                logger.warning("AI writer crashed (attempt %s): %r", attempt, exc)
                warnings.append("The AI writer failed. Used the built-in prompt writer instead.")
                return None, warnings
            text = clean_llm_text(raw)
            check = validate_llm_prompt(text, facts, options.aspect_ratio, duration, has_reference)
            if check.ok:
                return text, warnings
            logger.info("AI prompt rejected (attempt %s): %s", attempt, check.problems)
            feedback, previous = check.problems, text
        warnings.append("The AI writer's answer broke the rules (" + "; ".join((feedback or [])[:2]) + "). Used the built-in prompt writer instead.")
        return None, warnings
