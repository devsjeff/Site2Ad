"""On-screen text: short messages that name the brand and fit the kind of ad.

Every word is either a verified fact, something the user typed, or a neutral pattern from the catalog. A pattern whose
value is unknown is skipped, so a missing offer never becomes an invented offer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .. import catalog

CAPTION_MAX_CHARS = 70
QUOTE_MAX_CHARS = 90
DANGLING_WORDS = {"in", "on", "at", "of", "for", "to", "and", "or", "the", "a", "an", "with", "from", "by", "across", "your", "our", "every", "each", "that", "which", "who", "more", "very"}

# Page-title leftovers that are not part of a brand name.
TITLE_NOISE = {"home", "homepage", "home page", "welcome", "official site", "official website", "index", "main"}
OCCASIONS = (
    "Diwali", "Holi", "Navratri", "Dussehra", "Eid", "Onam", "Pongal", "Raksha Bandhan", "Ganesh Chaturthi", "Christmas",
    "New Year", "IPL", "Black Friday", "Valentine's Day", "Independence Day", "Republic Day",
)


def short_caption(text: str) -> str:
    """One readable caption: the first sentence, cut at a clause or word boundary when it is long."""
    sentence = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))[0].rstrip(".")
    if len(sentence) <= CAPTION_MAX_CHARS:
        return sentence
    clause = re.split(r"\s*[–—]\s*|[,;:]\s|\s-\s", sentence)[0]  # em/en dashes split even without spaces
    if 12 <= len(clause) <= CAPTION_MAX_CHARS:
        return clause
    # cut before a trailing phrase ("... in Mumbai, Delhi"), never leaving a dangling "in", "and", "the" at the end
    words = sentence[:CAPTION_MAX_CHARS].rsplit(" ", 1)[0].split()
    for joiner in (" in ", " across ", " for ", " with ", " at ", " from "):
        head = " ".join(words).rsplit(joiner, 1)[0]
        if head != " ".join(words) and len(head) >= 20:
            words = head.split()
            break
    while len(words) > 3 and words[-1].lower() in DANGLING_WORDS:
        words.pop()
    return " ".join(words).rstrip(",;:")


def brand_name(name: str) -> str:
    """The name people say, not the page title: 'Home | Night Owl Cafe - Best Coffee' -> 'Night Owl Cafe'."""
    clean = " ".join((name or "").split())
    parts = [p.strip() for p in re.split(r"\s*[|•·»]\s*|\s[–—-]\s", clean) if p.strip()]
    useful = [p for p in parts if p.lower() not in TITLE_NOISE]
    return (useful or parts or [clean])[0]


def domain_of(url: str) -> str:
    """'https://www.nightowl.in/menu' -> 'nightowl.in'."""
    value = (url or "").strip()
    host = urlparse(value if "//" in value else f"//{value}").hostname or ""
    return host.removeprefix("www.")


def real_quote(instructions: str) -> str:
    """A customer quote the user pasted in "double quotes"; empty when there is none (reviews are never invented)."""
    match = re.search(r"[\"“]([^\"”]{8,%d})[\"”]" % QUOTE_MAX_CHARS, instructions or "")
    return f"“{' '.join(match.group(1).split())}”" if match else ""


def occasion_in(instructions: str) -> str:
    """The festival or occasion the user named; 'this season' otherwise."""
    for occasion in OCCASIONS:
        if re.search(rf"\b{re.escape(occasion)}\b", instructions or "", re.I):
            return occasion
    return "this season"


def ad_captions(
    ad_type: str, *, name: str, about: str = "", services: Optional[list[str]] = None, offer: str = "", phone: str = "", website: str = "",
    place: str = "", instructions: str = "",
) -> list[str]:
    """Up to three messages for this kind of ad, in story order, with the brand named. Empty for "auto"."""
    service = (services or [""])[0]
    values = {
        "name": name, "about": short_caption(about) if about else "", "service": service[:1].upper() + service[1:], "offer": short_caption(offer) if offer else "",
        "phone": phone, "domain": domain_of(website), "place": place, "quote": real_quote(instructions), "occasion": occasion_in(instructions),
    }
    captions: list[str] = []
    seen: set[str] = set()
    for pattern in catalog.ad_type_info(ad_type)["captions"]:
        wanted = re.findall(r"{(\w+)}", pattern)
        if not all(values.get(key) for key in wanted):
            continue
        if "{offer}" in pattern and any(values["offer"] in c for c in captions):
            continue  # "{offer}" and "{offer} at {name}" are alternatives
        text = pattern.format(**values)
        limit = QUOTE_MAX_CHARS if "{quote}" in pattern else CAPTION_MAX_CHARS
        text = text if len(text) <= limit else short_caption(text)
        text = text[:1].upper() + text[1:]
        if text.lower() not in seen:
            seen.add(text.lower())
            captions.append(text)
    return captions[:3]


def place_of(address: str) -> str:
    """The town of an address: the last part that is not a number, PIN code or country."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    towns = [p for p in parts if not re.search(r"\d", p) and p.lower() not in {"india", "bharat"}]
    return towns[-1] if len(parts) > 1 and towns else ""


# ------------------------------------------------------------------ duration-fitted text plan

BEATS = {
    2: ("hook", "close"),
    3: ("hook", "value", "close"),
    4: ("hook", "value", "detail", "close"),
    5: ("hook", "value", "detail", "extra", "close"),
}
MIN_READ_SECONDS = 2.0


@dataclass(frozen=True)
class TextPlan:
    """How much text fits: one line per beat, each readable for at least two seconds."""

    count: int
    max_chars: int
    max_words: int
    seconds_each: float

    @property
    def beats(self) -> tuple[str, ...]:
        """The story role of each line, in order."""
        return BEATS[self.count]


def text_plan(duration: float, platform: str) -> TextPlan:
    """5 s -> 2 lines, 10 s -> 3, 15 s -> 4, 20 s -> 5; line length from where the ad is watched (a cab tablet needs the fewest words)."""
    count = 2 if duration <= 7 else 3 if duration <= 12 else 4 if duration <= 17 else 5
    info = catalog.PLATFORMS.get(platform, catalog.PLATFORMS["taxi_screen"])
    return TextPlan(count, info["max_chars"], info["max_words"], round(max(MIN_READ_SECONDS, duration / count), 2))


SENTENCE_KEYS = ("service", "service2", "about")


# Menu and button text scraped as "services" that is not something the business sells.
NOT_A_SERVICE = {
    "dine", "order", "book", "contact", "about", "login", "log", "sign", "register", "subscribe", "download", "visit", "call", "buy", "shop",
    "get", "find", "view", "read", "learn", "explore", "join", "apply", "careers", "career", "jobs", "faq", "blog", "news", "home", "menu",
    "locations", "location", "stores", "store", "offers", "deals", "catering", "franchise", "gift", "track", "support", "help", "terms", "privacy",
}


def usable_services(services: list[str], name: str) -> list[str]:
    """Services that read as a product or service on screen: not menu text, not the brand repeated, short enough to say at a glance."""
    brand = name.lower().split()
    clean: list[str] = []
    for service in services:
        text = " ".join(service.split())
        words = text.lower().split()
        if not 1 <= len(words) <= 4 or words[0] in NOT_A_SERVICE or (brand and " ".join(brand) in text.lower()):
            continue
        if re.search(r"\d|@|https?:|\b(by|with|near|for|from)\b", text, re.I) or text.lower() in {c.lower() for c in clean}:
            continue
        clean.append(text)
    return clean


def _mid(text: str) -> str:
    """'Chicken biryani' inside a sentence reads 'chicken biryani'; Title Case and acronyms are kept as the site wrote them."""
    return text[:1].lower() + text[1:] if text[:1].isupper() and text[1:] == text[1:].lower() else text


def _base_values(*, name: str, about: str, offer: str, phone: str, website: str, place: str, instructions: str) -> dict[str, str]:
    """Everything a line pattern may use besides the services; empty means unknown."""
    return {
        "name": name, "about": short_caption(about) if about else "", "offer": short_caption(offer) if offer else "",
        "phone": phone, "domain": domain_of(website), "place": place, "quote": real_quote(instructions), "occasion": occasion_in(instructions),
    }


def _render(pattern: str, values: dict[str, str], max_chars: int) -> tuple[str, set[str]]:
    """(the line, the keys it used) for a pattern; ("", set()) when a value is unknown or the line is too long to read at a glance."""
    wanted = re.findall(r"{(\w+)}", pattern)
    if not all(values.get(key) for key in wanted):
        return "", set()
    shown = {key: (_mid(values[key]) if key in SENTENCE_KEYS and not pattern.startswith("{" + key + "}") else values[key]) for key in wanted}
    text = pattern.format(**shown)
    text = text[:1].upper() + text[1:]
    return (text, set(wanted)) if len(text) <= (QUOTE_MAX_CHARS if "{quote}" in pattern else max_chars) else ("", set())


def plan_captions(
    ad_type: str, playbook, *, plan: TextPlan, name: str, about: str = "", services: Optional[list[str]] = None, offer: str = "", phone: str = "",
    website: str = "", place: str = "", instructions: str = "",
) -> list[str]:
    """One line per beat (hook, value, detail, close), from the kind of ad first and the category playbook after it.

    Each line names a different real service, so a restaurant ad says which dish and then the next one. Only facts that
    exist are used. The last line always invites an action; at least one line names the brand.
    """
    from .playbook import GENERAL  # imported here: playbook.py imports the formula module

    base = _base_values(name=name, about=about, offer=offer, phone=phone, website=website, place=place, instructions=instructions)
    typed = list(catalog.ad_type_info(ad_type)["captions"])
    pools = {
        "hook": typed[:1] + list(playbook.hook) + list(GENERAL.hook),
        "value": typed[1:-1] + list(playbook.value) + list(GENERAL.value),
        "detail": list(playbook.detail) + list(GENERAL.detail),
        "extra": ["{offer}"] + list(playbook.value[1:]) + list(playbook.detail),
        "close": typed[-1:] + list(playbook.close) + list(GENERAL.close),
    }
    unused = usable_services(services or [], name)
    lines: list[str] = []
    for beat in plan.beats:
        for pattern in pools[beat]:
            values = {**base, "service": unused[0] if unused else "", "service2": unused[1] if len(unused) > 1 else ""}
            text, used = _render(pattern, values, plan.max_chars)
            if text and text.lower() not in {line.lower() for line in lines}:
                lines.append(text)
                unused = [s for i, s in enumerate(unused) if not (("service" in used and i == 0) or ("service2" in used and i == 1))]
                break
    if lines and name and not any(name.lower() in line.lower() for line in lines):
        for pattern in list(playbook.close) + list(GENERAL.close):  # the brand is always named
            text, _ = _render(pattern, {**base, "service": "", "service2": ""}, plan.max_chars)
            if text and "{name}" in pattern:
                lines[-1] = text
                break
    return lines


def fill_captions(written: list[str], pattern: list[str], count: int) -> list[str]:
    """The AI's lines, topped up with pattern lines when it wrote fewer than planned."""
    lines = list(written[:count])
    for line in pattern:
        if len(lines) >= count:
            break
        if line.lower() not in {existing.lower() for existing in lines}:
            lines.append(line)
    return lines
