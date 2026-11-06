"""The voiceover in another language.

The storyboard is written and verified in English (every claim, figure and price is checked against the website notes). For a video
spoken in another language, only the voice lines are translated, in one request, and the translation is checked in code: it must keep
every figure of the English line and add none, must not be empty, and must fit the time of its shot. The words on screen stay as the
website wrote them. A line is translated again only when its English changed (the check stage may reword a shot), and when the AI writer
cannot translate, the video is simply spoken in English instead of failing.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import catalog
from .ai import ask_json
from .config import StageError, words_limit
from .figures import figure_key, figures_in, is_trivial

logger = logging.getLogger(__name__)

SYSTEM = """You translate the voice-over lines of a short advertising video into {language} ({native}). Answer with ONE JSON object only:
{{"lines": [{{"n": int, "text": str}}, ...]}}

RULES
- One entry for every line you are given, with the same "n". Keep the meaning exactly: add no claim, no figure, no adjective that is not in the English line; leave nothing out.
- Natural spoken {language}, as a warm professional announcer would say it. Short sentences. No quotation marks, no emoji, no hashtags.
- Write every figure with ordinary digits 0-9, exactly as in the English line (4,000 stays 4,000; 18% stays 18%). Write a currency as a word in {language} after the number (rupees, dollars...), never as a symbol.
- Keep the business and product names in Latin letters as written. Keep website addresses as written.
- Each line has a word limit ("max_words"). Stay within it by choosing shorter words, not by dropping facts."""


def _figure_keys(text: str) -> set[str]:
    return {figure_key(token) for token in figures_in(text) if not is_trivial(token)}


def validate_translation(data: dict, wanted: list[dict]) -> list[str]:
    """Problems of an answer (empty when it is good)."""
    lines = data.get("lines")
    if not isinstance(lines, list):
        return ['answer with {"lines": [{"n": 1, "text": "..."}, ...]}']
    by_n = {}
    for item in lines:
        if isinstance(item, dict) and isinstance(item.get("n"), int) and isinstance(item.get("text"), str):
            by_n[item["n"]] = item["text"].strip()
    problems = []
    for entry in wanted:
        text = by_n.get(entry["n"], "")
        if not text:
            problems.append(f"line {entry['n']} is missing")
            continue
        if len(text.split()) > entry["max_words"]:
            problems.append(f"line {entry['n']} has {len(text.split())} words but at most {entry['max_words']} fit its shot; make it shorter")
        have, need = _figure_keys(text), _figure_keys(entry["english"])
        if need - have:
            problems.append(f"line {entry['n']} lost the figure(s) {sorted(need - have)}; keep every figure with ordinary digits")
        if have - need:
            problems.append(f"line {entry['n']} has the figure(s) {sorted(have - need)} that the English line does not have; remove them")
    return problems


def translate_lines(wanted: list[dict], language: str) -> dict[int, str]:
    """{shot number: the line in `language`} for the given {n, english, max_words} entries (asks the AI writer; checked in code)."""
    info = catalog.LANGUAGES[language]
    user = "Lines to translate:\n" + "\n".join(f'{{"n": {e["n"]}, "max_words": {e["max_words"]}, "english": {e["english"]!r}}}' for e in wanted) + "\n\nTranslate them now."
    data = ask_json(SYSTEM.format(language=info["label"], native=info["native"]), user, lambda d: validate_translation(d, wanted), what="translation", max_tokens=1800, tries=3)
    return {item["n"]: item["text"].strip() for item in data["lines"] if isinstance(item, dict) and isinstance(item.get("n"), int) and isinstance(item.get("text"), str)}


def ensure_translations(board: dict[str, Any], language: str) -> str:
    """Make sure every shot with a voice line has its `voice_local` for `language`. Returns "" when done, or a note when it fell back to English.

    Shots keep `voice_src` (the English line that was translated); a shot whose English changed is translated again, the others are kept.
    """
    shots = board["shots"]
    if language == "en":
        return ""
    todo = [s for s in shots if s["voice"].strip() and (s.get("voice_src") != s["voice"] or not s.get("voice_local"))]
    if not todo:
        return ""
    wanted = [{"n": s["n"], "english": s["voice"], "max_words": max(3, round(words_limit(s["seconds"]) * 1.1))} for s in todo]
    try:
        lines = translate_lines(wanted, language)
    except StageError as exc:
        logger.info("translation to %s failed: %s", language, exc)
        for shot in shots:
            shot.pop("voice_local", None)
            shot.pop("voice_src", None)
        return f"The voice-over could not be translated to {catalog.LANGUAGES[language]['label']} ({str(exc)[:160]}), so it is spoken in English."
    for shot in todo:
        shot["voice_local"], shot["voice_src"] = lines[shot["n"]], shot["voice"]
    return ""
