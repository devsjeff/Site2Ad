"""PromptBuilder: facts + options -> exactly ONE AdPrompt (AI writer first, deterministic template as the safety net)."""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..config import Settings
from .. import catalog
from ..schemas import AdBrief, AdOptions, AdPrompt, ReferenceImage
from .facts import FactSheet
from .guard import PROMPT_MAX_CHARS, find_unsupported_facts, validate_llm_prompt
from .llm import SYSTEM_PROMPT, LlmClient, LlmError, build_user_message
from .director import DIRECTOR_SYSTEM_PROMPT, build_director_request, film_problems, finish_clip_prompt, parse_film
from .brief import BRIEF_SYSTEM_PROMPT, build_brief_request, build_template_brief, merge_llm_brief, parse_llm_brief
from .scene import SCENE_AVOID, build_scene_prompt
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


# Lines dropped first when a video model accepts only short prompts (least useful to the picture first).
DROP_ORDER = ("ABOUT:", "EXTRA DIRECTION", "AUDIO:", "BRAND COLOURS:", "GOAL:", "TONE:", "OFFERING:")
SHORT_NEGATIVE = (
    "text, letters or numbers drawn by the model, invented logos, watermarks, warped faces and hands, blurry frames, flicker"
)


def fit_prompt(positive: str, negative: str, limit: int) -> tuple[str, str]:
    """Shorten a prompt to `limit` characters for video models with a hard cap (Magic Hour: 2000).

    Order: compact the negative list and the text-overlay line, drop optional lines (least important first), shorten the
    shot actions, and only then cut at a word boundary. The shot lines (camera, motion, action) are kept to the end.
    """
    def total(pos: str, neg: str) -> int:
        """Length of the final prompt."""
        return len(f"{pos}\n\nNEGATIVE PROMPT: {neg}")

    if total(positive, negative) <= limit:
        return positive, negative
    negative = SHORT_NEGATIVE
    lines = positive.splitlines()
    lines = ["TEXT OVERLAYS: added in editing; draw no text in the video." if l.startswith("TEXT OVERLAYS:") else l for l in lines]
    for prefix in DROP_ORDER:
        if total("\n".join(lines), negative) <= limit:
            break
        lines = [l for l in lines if not l.startswith(prefix)]
    if total("\n".join(lines), negative) > limit:  # compact wording, never the structure the guard checks
        compact = []
        for line in lines:
            if line.startswith("FORMAT:"):
                line = re.sub(r" \([^)]*\)\.?$", ".", line)  # drop the audience description
            elif line.startswith("LOOP:"):
                line = "LOOP: the clip repeats, so end with the same framing, light and colours as the opening; smooth continuous motion, no hard ending."
            elif line.startswith("REFERENCE IMAGE: none"):
                line = "REFERENCE IMAGE: none supplied; realistic visuals, no invented logos."
            elif SHOT_RE.match(line):
                for label in ("Camera", "Lighting"):  # keep the first phrase of each description
                    line = re.sub(rf"({label}: [^,;]*)[^;]*", r"\1", line)
                line = re.sub(r"(Action: [^.]*\.).*$", r"\1", line)  # keep the first sentence of the action
            compact.append(line)
        lines = compact
    positive = "\n".join(lines)
    room = limit - total("", negative)
    if len(positive) > room:
        positive = positive[:room].rsplit(" ", 1)[0].rstrip(" ,;:")
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
    def video_prompt_limit(self) -> int:
        """Longest prompt the configured video model accepts (0 = no limit beyond our own)."""
        if self.settings.effective_video_provider == "magic_hour":
            return self.settings.video_prompt_max_chars
        return 0

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
        limit = self.video_prompt_limit
        if limit and len(f"{positive}\n\nNEGATIVE PROMPT: {negative}") > limit:
            positive, negative = fit_prompt(positive, negative, limit)
            warnings.append(f"The prompt was shortened to {limit} characters, the most the video model accepts.")
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

    async def build_brief(
        self, facts: FactSheet, options: AdOptions, *, duration_seconds: int, include_logo: bool = True, include_qr: bool = False,
    ) -> tuple[AdBrief, list[str]]:
        """The validated Ad Brief: the AI writer's creative ideas when configured and valid, else the built-in brief.

        Facts (CTA, offer, overlay text, supporting facts) always come from the FactSheet; the AI only shapes the idea.
        """
        base = build_template_brief(facts, options, duration_seconds=duration_seconds, include_logo=include_logo, include_qr=include_qr)
        if not self.llm.enabled:
            return base, []
        try:
            raw = await self.llm.complete(BRIEF_SYSTEM_PROMPT, build_brief_request(facts, options, duration_seconds))
        except LlmError as exc:
            return base, [f"{exc} Used the built-in ad brief instead."]
        except Exception as exc:  # defensive: the ad must not fail because of the writer
            logger.warning("AI brief writer crashed: %r", exc)
            return base, ["The AI writer failed. Used the built-in ad brief instead."]
        draft = parse_llm_brief(raw)
        if draft is None:
            logger.info("AI brief was not valid JSON for the brief schema; using the built-in brief")
            return base, ["The AI writer's brief was malformed. Used the built-in ad brief instead."]
        return merge_llm_brief(base, draft, facts)

    async def build_film(
        self, facts: FactSheet, options: AdOptions, brief: Optional[AdBrief], *, clips: int, clip_seconds: int,
        reference: Optional[ReferenceImage] = None,
    ) -> tuple[Optional[list[AdPrompt]], list[str]]:
        """Shot-by-shot prose prompts written by the AI director, one per clip (None when no AI writer or no valid plan)."""
        if not self.llm.enabled:
            return None, []
        limit = self.video_prompt_limit or PROMPT_MAX_CHARS
        system = DIRECTOR_SYSTEM_PROMPT.replace("{limit}", str(limit))
        user = build_director_request(
            facts, options, brief, clips=clips, clip_seconds=clip_seconds, has_reference=reference is not None, limit=limit,
        )
        for attempt in range(1, LLM_ATTEMPTS + 1):
            try:
                raw = await self.llm.complete(system, user, max_tokens=900 + 700 * clips)
            except LlmError as exc:
                return None, [f"{exc} Used the built-in scene prompt instead."]
            except Exception as exc:  # defensive: the ad must not fail because of the writer
                logger.warning("AI director crashed: %r", exc)
                return None, ["The AI director failed. Used the built-in scene prompt instead."]
            film = parse_film(raw)
            problems = ["the answer was not the requested JSON"] if film is None else film_problems(film, facts, clips)
            if film is not None and not problems:
                prompts = [
                    AdPrompt(
                        final_prompt=(text := finish_clip_prompt(film, index, limit)), positive_prompt=text, negative_prompt=SCENE_AVOID,
                        platform=options.platform, duration_seconds=clip_seconds, aspect_ratio=options.aspect_ratio,
                        shot_count=max(1, len(re.findall(r"(?i)\bshot\s*\d", film.clips[index].prompt))), builder="llm",
                        model=self.llm.model, reference_image=reference if index == 0 else None,
                    )
                    for index in range(clips)
                ]
                return prompts, []
            logger.info("AI director plan rejected (attempt %s): %s", attempt, problems)
            user += "\n\nYour previous answer had these problems; fix them and answer with the full JSON again: " + "; ".join(problems[:4])
        return None, ["The AI director's plan broke the rules. Used the built-in scene prompt instead."]

    async def build_scene(
        self, facts: FactSheet, options: AdOptions, *, reference: Optional[ReferenceImage] = None, duration_seconds: Optional[int] = None,
        loop_seconds: int = 0, brief: Optional[AdBrief] = None,
    ) -> AdPrompt:
        """ONE scene prompt for an AI video model, built from the brief's chosen concept (one continuous shot, plain sentences).

        Offers, prices, phone numbers and addresses are kept out: exact text is added afterwards by FFmpeg.
        """
        duration = int(duration_seconds or options.duration_seconds)
        warnings: list[str] = []
        if brief is None:
            brief, warnings = await self.build_brief(facts, options, duration_seconds=duration)
        limit = self.video_prompt_limit or PROMPT_MAX_CHARS
        text = build_scene_prompt(
            facts, style=options.style, aspect_ratio=options.aspect_ratio, has_reference=reference is not None,
            looping=loop_seconds > duration, notes=facts.user_notes, visual=brief.concept.visual,
            mood=catalog.TONES.get(options.tone, {}).get("mood", ""),
        )
        if len(text) > limit:
            text = text[:limit].rsplit(" ", 1)[0]
            warnings.append(f"The prompt was shortened to {limit} characters, the most the video model accepts.")
        problems = [p for p in find_unsupported_facts(text, facts)]
        if problems:  # a concept slipped something through: fall back to the built-in concept (never send unsupported facts)
            warnings.append("The scene repeated an unsupported fact, so the built-in scene was used.")
            text = build_scene_prompt(
                facts, style=options.style, aspect_ratio=options.aspect_ratio, has_reference=reference is not None,
                looping=loop_seconds > duration, notes="",
            )[:limit]
        return AdPrompt(
            final_prompt=text, positive_prompt=text, negative_prompt=SCENE_AVOID, platform=options.platform, duration_seconds=duration,
            aspect_ratio=options.aspect_ratio, shot_count=len(brief.concept.scenes) or 1, builder=brief.builder,
            model=self.llm.model if brief.builder == "llm" else "", reference_image=reference, warnings=warnings,
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
