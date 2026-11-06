"""Stage 4, ASSUMPTIONS: the choices the AI makes for you (audience, one key message, tone, voice, music, must-include, must-avoid).

They are written to 04_assumptions.json and 04_assumptions.md and printed, so you can correct them. Edit the JSON file
and run the next stage: the storyboard reads exactly what is in the file.

Files: 04_assumptions.json, 04_assumptions.md
"""

from __future__ import annotations

import re
from typing import Any

from .. import catalog
from ..video import voice as voice_engine
from .ai import ask_json
from .config import Run, VIDEO_TYPES

VOICE_IDS = [v for v in catalog.VOICES if v not in {"auto", "none"}]
MUSIC_IDS = [m for m in catalog.MUSIC if m not in {"auto"}]

SYSTEM_TEMPLATE = """You decide the creative direction of ONE short video, from the product notes and brand notes. Answer with ONE JSON object only:
{{"audience": str, "key_message": str, "tone": str, "voice": str, "voice_reason": str, "music": str, "music_reason": str,
 "cta_text": str, "cta_target": str, "must_include": [{{"what": str, "claims": ["C1"]}}], "must_avoid": [str]}}

RULES
- audience: the one group this video speaks to (at most 20 words).
- key_message: ONE sentence of at most 14 words that the viewer must remember. It must be supported by the claims.
- tone: at most 12 words, fitting the brand tone and the video type.
- voice: the voice-over will be spoken in {language}. Pick one of these voices (id: description), the one that fits the brand, the audience and the video type: {voices}.
- music: one of {music} ("upbeat" energetic, "calm" gentle, "premium" slow and refined, "none" silent).
- cta_text: the one thing to do, copied from a real button or link on the page (at most 4 words). cta_target: where it goes (a domain or page name).
- must_include: 2 to 4 things the video must show or say. Each cites the claim ids that support it. Only sourced claims.
- must_avoid: 2 to 4 things to keep out (for example claims that are not sourced, other companies, anything misleading).
- Use only the claims given. Never add a figure that is not in a claim."""


def voice_choices(language: str) -> list[str]:
    """Voice ids that speak `language` (ElevenLabs ones only while that engine works)."""
    return catalog.voices_for(language, eleven=voice_engine.eleven_ready())


def default_voice(language: str, ids: list[str]) -> str:
    """The voice used when the AI picks none that fits: an ElevenLabs one when available (the most natural), else a Microsoft voice."""
    studio = [v for v in ids if catalog.VOICES[v]["engine"] == "eleven"]
    return studio[0] if studio else (ids[0] if ids else catalog.default_voice(language))


def system_prompt(language: str, ids: list[str]) -> str:
    voices = "; ".join(f"{v}: {catalog.VOICES[v]['hint'].lower()} ({'ElevenLabs studio voice' if catalog.VOICES[v]['engine'] == 'eleven' else 'free voice'})" for v in ids)
    return SYSTEM_TEMPLATE.format(language=catalog.LANGUAGES[language]["label"], voices=voices, music=MUSIC_IDS)


def build_assumptions(run: Run, video_type: str) -> dict[str, Any]:
    """Run stage 4."""
    notes = run.read(run.product_json, "notes")
    brand = run.read(run.brand_json, "brand")
    capture = run.read(run.capture_json, "capture")
    request = run.request()
    language = request.get("language", "en")
    voice_ids = voice_choices(language)
    chosen = request.get("voice", "auto")  # a voice picked on the form is used as it is
    if chosen != "auto" and chosen not in voice_ids:
        chosen = "auto"  # (an ElevenLabs voice whose engine has since switched off): let the writer pick
    claims = "\n".join(f"{c['id']} [{c['kind']}] {c['text']}" for c in notes["claims"])
    buttons = ", ".join(sorted({b["text"] for b in capture["blocks"] if b["button"] and 2 < len(b["text"]) < 30}))[:600]
    user = (
        f"Video type: {video_type}\n\nWhat it is: {notes['what_it_is']}\nWho it is for: {notes['who_for']}\n\nClaims:\n{claims}\n\n"
        f"Brand tone: {brand['tone']} ({', '.join(brand['tone_words'])})\nBrand fonts: {brand['fonts']['heading']} / {brand['fonts']['body']}\n"
        f"Real buttons and links on the page: {buttons}\n\nDecide the direction now."
    )
    ids = {c["id"] for c in notes["claims"]}

    def check(data: dict) -> list[str]:
        problems = []
        if data.get("music") not in MUSIC_IDS:
            problems.append(f"music must be one of {MUSIC_IDS}")
        for field in ("audience", "key_message", "tone", "cta_text", "cta_target"):
            if not str(data.get(field, "")).strip():
                problems.append(f"{field} is required")
        if len(str(data.get("key_message", "")).split()) > 18:
            problems.append("key_message must be one short sentence (at most 14 words)")
        items = data.get("must_include")
        if not isinstance(items, list) or not items:
            problems.append("must_include needs 2 to 4 items")
        else:
            for item in items:
                refs = item.get("claims") if isinstance(item, dict) else None
                if not refs or not all(r in ids for r in refs):
                    problems.append(f"must_include item {item!r} must cite existing claim ids ({sorted(ids)[:6]}...)")
                    break
        if not isinstance(data.get("must_avoid"), list) or not data["must_avoid"]:
            problems.append("must_avoid needs 2 to 4 items")
        return problems

    data = ask_json(system_prompt(language, voice_ids), user, check, what="assumptions", max_tokens=1600)
    voice = chosen if chosen != "auto" else data.get("voice") if data.get("voice") in voice_ids else default_voice(language, voice_ids)  # a wrong pick is fixed here, not sent back
    assumptions = {
        "video_type": video_type, "audience": " ".join(str(data["audience"]).split()), "key_message": " ".join(str(data["key_message"]).split()),
        "tone": " ".join(str(data["tone"]).split()), "voice": voice,
        "voice_reason": str(data.get("voice_reason", "")).strip() if voice == data.get("voice") else "the voice you chose" if chosen != "auto" else "a good match for the language",
        "language": language, "sound_effects": bool(request.get("sound_effects", True)),
        "music": data["music"], "music_reason": str(data.get("music_reason", "")).strip(),
        "cta": {"text": " ".join(str(data["cta_text"]).split()), "target": " ".join(str(data["cta_target"]).split())},
        "must_include": [{"what": str(i["what"]).strip(), "claims": list(i["claims"])} for i in data["must_include"][:4]],
        "must_avoid": [str(a).strip() for a in data["must_avoid"][:4]],
    }
    run.write_json(run.assumptions_json, assumptions)
    write_assumptions_md(run, assumptions)
    return assumptions


def write_assumptions_md(run: Run, a: dict) -> None:
    """04_assumptions.md: the same choices in words, with the instruction to correct them."""
    out = [f"# Assumptions for the {a['video_type']} video", "",
           "These are my guesses. To correct one, edit **04_assumptions.json** and run the next stage; the storyboard reads that file.", "",
           f"- **Audience:** {a['audience']}", f"- **One key message:** {a['key_message']}", f"- **Tone:** {a['tone']}",
           f"- **Language:** {catalog.LANGUAGES.get(a.get('language', 'en'), {}).get('label', 'English')}", f"- **Voice:** {a['voice']} ({a['voice_reason']})",
           f"- **Music:** {a['music']} ({a['music_reason']})", f"- **Sound effects:** {'on' if a.get('sound_effects', True) else 'off'}",
           f"- **Call to action:** {a['cta']['text']} ({a['cta']['target']})", "- **Must include:**"]
    out += [f"  - {i['what']} (claims {', '.join(i['claims'])})" for i in a["must_include"]]
    out += ["- **Must avoid:**"] + [f"  - {x}" for x in a["must_avoid"]]
    run.assumptions_md.write_text("\n".join(out) + "\n", encoding="utf-8")


def validate_edited(a: dict, notes: dict) -> list[str]:
    """Problems in a hand-edited assumptions file (so a typo fails early with a clear message)."""
    problems = []
    language = a.get("language", "en")
    if language not in catalog.LANGUAGES:
        problems.append(f"language '{language}' is not one of {list(catalog.LANGUAGES)}")
    elif a.get("voice") not in VOICE_IDS + ["none"]:
        problems.append(f"voice '{a.get('voice')}' is not one of {VOICE_IDS}")
    elif a.get("voice") != "none" and language not in catalog.VOICES[a["voice"]]["languages"]:
        problems.append(f"the voice '{a['voice']}' does not speak {catalog.LANGUAGES[language]['label']}; choose one of: {', '.join(catalog.voices_for(language))}")
    if a.get("music") not in MUSIC_IDS:
        problems.append(f"music '{a.get('music')}' is not one of {MUSIC_IDS}")
    if a.get("video_type") not in VIDEO_TYPES:
        problems.append(f"video_type '{a.get('video_type')}' is not one of {list(VIDEO_TYPES)}")
    ids = {c["id"] for c in notes["claims"]}
    for item in a.get("must_include", []):
        bad = [r for r in item.get("claims", []) if r not in ids]
        if bad:
            problems.append(f"must_include '{item.get('what')}' cites unknown claims {bad}")
    if not re.search(r"\w", str(a.get("cta", {}).get("text", ""))):
        problems.append("cta.text is empty")
    return problems
