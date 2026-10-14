"""Fact guard and prompt validator.

The video prompt may only contain facts that exist in the FactSheet. This module finds numbers, prices, contact
details and marketing claims in a generated prompt that are NOT backed by the facts, and checks that an LLM
answer has the required shape (one ad, 3-6 shots, negative prompt, ...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .facts import FactSheet

PROMPT_MAX_CHARS = 3600
MIN_SHOTS, MAX_SHOTS = 3, 6

# Claims that must never appear unless the website/user said them.
RISKY_CLAIMS = (
    "guarantee", "money-back", "money back", "award-winning", "award winning", "#1", "number one", "no. 1", "best in",
    "lowest price", "cheapest", "free delivery", "free shipping", "free home delivery", "24/7", "24x7", "open daily",
    "years of experience", "certified", "licensed", "iso 9001", "five-star", "5-star", "best-selling", "bestselling",
    "world-class", "market leader", "trusted by", "voted", "rated", "no hidden", "risk-free", "risk free",
    "100% satisfaction", "100% natural", "100% organic", "limited stock", "while stocks last", "sale ends",
)
MULTI_CONCEPT_RE = re.compile(r"\b(option|concept|version|alternative|variant|idea)\s*(\d|[a-c]\b|one|two|three)", re.I)
PHONE_RE = re.compile(r"(?<![\d.])\+?\(?\d[\d\s().\-]{5,}\d(?![\d])")
PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
MONEY_RE = re.compile(r"(?:rs\.?|inr|₹|\$|usd|€|£)\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:rs\b|inr\b|rupees|dollars|usd\b)", re.I)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s\"'<>)]+|\b[a-z0-9][a-z0-9\-]*\.(?:com|in|net|org|co|io|shop|store|app|biz|info)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
SHOT_LABEL_RE = re.compile(r"(?im)\bSHOT\s+\d+\s*(?:\(\s*\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds)?\s*\))?")
TIME_RANGE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds)\b", re.I)
YEAR_CLAIM_RE = re.compile(r"\b(?:since|est\.?|established|founded(?: in)?)\s+(\d{4})\b|\b(\d{1,3})\+?\s+years?\b", re.I)


def _has_phrase(text: str, phrase: str) -> bool:
    """True when `phrase` appears as whole words; a single plain word also matches its endings (guarantee -> guaranteed)."""
    ending = r"\w*" if phrase.isalpha() else r"(?!\w)"
    return re.search(r"(?<!\w)" + re.escape(phrase) + ending, text) is not None


def _digits(text: str) -> str:
    """Digits only."""
    return re.sub(r"\D", "", text)


@dataclass
class PromptCheck:
    """Outcome of validating a prompt."""

    ok: bool
    problems: list[str]


def find_unsupported_facts(prompt: str, facts: FactSheet) -> list[str]:
    """Return human readable problems for anything in `prompt` that the facts do not support."""
    problems: list[str] = []
    allowed = facts.allowed_text()
    allowed_digits = _digits(allowed)
    prompt = TIME_RANGE_RE.sub(" ", SHOT_LABEL_RE.sub("SHOT", prompt))  # shot numbers and time windows are not facts
    allowed_compact = re.sub(r"\s+", "", allowed)

    for match in PHONE_RE.finditer(prompt):
        digits = _digits(match.group(0))
        if len(digits) >= 7 and digits not in allowed_digits:
            problems.append(f"phone number or long number not in the facts: {match.group(0).strip()}")
    for match in PERCENT_RE.finditer(prompt):
        number = match.group(1)
        if not re.search(r"(?<![\d.])" + re.escape(number) + r"\s?%", allowed):
            problems.append(f"percentage not in the facts: {match.group(0)}")
    for match in MONEY_RE.finditer(prompt):
        number = (match.group(1) or match.group(2) or "").replace(",", "")
        if number and number not in allowed.replace(",", ""):
            problems.append(f"price not in the facts: {match.group(0).strip()}")
    for match in URL_RE.finditer(prompt):
        url = match.group(0).lower().rstrip(".,;")
        bare = re.sub(r"^(https?://)?(www\.)?", "", url).split("/")[0]
        if bare not in allowed_compact and bare not in allowed:
            problems.append(f"web address not in the facts: {match.group(0)}")
    for match in EMAIL_RE.finditer(prompt):
        if match.group(0).lower() not in allowed:
            problems.append(f"email not in the facts: {match.group(0)}")
    for match in YEAR_CLAIM_RE.finditer(prompt):
        number = match.group(1) or match.group(2)
        if number and not re.search(r"(?<!\d)" + number + r"(?!\d)", allowed):
            problems.append(f"year or experience claim not in the facts: {match.group(0)}")
    lowered = prompt.lower()
    for claim in RISKY_CLAIMS:
        if _has_phrase(lowered, claim) and not _has_phrase(allowed, claim):
            problems.append(f"marketing claim not in the facts: '{claim}'")
    return problems


def validate_llm_prompt(text: str, facts: FactSheet, aspect_ratio: str, duration_seconds: int, has_reference: bool) -> PromptCheck:
    """Check that an LLM answer is exactly ONE ad prompt with the required parts and no invented facts."""
    problems: list[str] = []
    if not text.strip():
        return PromptCheck(False, ["empty answer"])
    if len(text) > PROMPT_MAX_CHARS:
        problems.append(f"too long ({len(text)} characters, maximum {PROMPT_MAX_CHARS})")
    if re.search(r'^\s*[\[{]\s*"', text) or "```" in text:
        problems.append("must be plain text, not JSON or a code block")
    if MULTI_CONCEPT_RE.search(text):
        problems.append("contains several options/concepts; only ONE ad is allowed")
    if len(re.findall(r"(?im)^\s*NEGATIVE PROMPT\s*:", text)) != 1:
        problems.append("needs exactly one 'NEGATIVE PROMPT:' section")
    shot_lines = re.findall(r"(?im)^\s*SHOT\s+\d+\b.*$", text)
    if not (MIN_SHOTS <= len(shot_lines) <= MAX_SHOTS):
        problems.append(f"needs {MIN_SHOTS}-{MAX_SHOTS} shots, found {len(shot_lines)}")
    for line in shot_lines:
        lowered = line.lower()
        if not all(word in lowered for word in ("camera", "motion", "lighting")):
            problems.append(f"every shot needs Camera, Motion and Lighting: '{line.strip()[:50]}...'")
            break
    lowered_text = text.lower()
    if facts.name.lower() not in lowered_text:
        problems.append("business name is missing")
    if aspect_ratio not in text:
        problems.append(f"aspect ratio {aspect_ratio} is missing")
    if not re.search(rf"\b{duration_seconds}\s*(?:s|sec|secs|seconds)\b", lowered_text):
        problems.append(f"duration of {duration_seconds} seconds is missing")
    if has_reference and not ("reference image" in lowered_text and "first frame" in lowered_text):
        problems.append("needs a REFERENCE IMAGE instruction saying it is the exact first frame")
    if not has_reference and "first frame" in lowered_text:
        problems.append("mentions a first-frame reference image but none is attached")
    for label, value in (("offer", facts.offer), ("call to action", facts.cta)):
        if value and value.lower() not in lowered_text:
            problems.append(f"the {label} '{value}' must appear")
    problems.extend(find_unsupported_facts(text, facts))
    return PromptCheck(not problems, problems)
