"""Does a scraped claim belong to THIS business? A deterministic check, used before a claim can reach an ad.

A phrase that appears somewhere on a website is not automatically about the advertiser: news sites carry ads for
airlines, marketplaces list other brands, blogs quote other companies. The check works like this:

1. Brand-like words of the claim are its capitalised words that are not part of the business's core identity (name,
   category, domain, page title), are not ordinary words used in lower case elsewhere on the site, and do not appear on
   several pages of the site (the advertiser's own products usually do; a one-off ad does not).
2. A claim with such foreign brands must still share real words with the business, counted only in website text that
   does NOT itself contain those brands (so an ad that also leaked into the services list cannot vouch for itself).

Typed-in user facts are never checked: the user decides about those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

STOPWORDS = frozenset(
    "a an and are as at be by for from get has have in is it its new now of off on or our the this to up us we with you your "
    "only just more most all any each every per day days week weeks month today tonight order book call shop buy visit "
    "save free sale offer offers deal deals discount special limited time flat extra upto up-to".split()
)
# Capitalised words that are not other brands: calendar, festivals, and common marketing words.
GENERIC_PROPER = frozenset(
    "january february march april may june july august september october november december monday tuesday wednesday "
    "thursday friday saturday sunday spring summer autumn fall winter monsoon diwali holi eid christmas easter navratri "
    "pongal onam rakhi dussehra ramadan new year black cyber valentine valentines mother father mothers fathers "
    "get book order call shop buy visit save free sale offer deal discount special limited flat extra now today only".split()
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'&\-]+")


@dataclass
class Relevance:
    """Outcome of the check: `foreign` lists the brand-like words that do not belong to the business."""

    relevant: bool
    reason: str = ""
    foreign: tuple[str, ...] = ()


def _fold(word: str) -> str:
    """Lower case with a simple plural folded."""
    w = word.lower().strip("'&-")
    return w[:-1] if w.endswith("s") and len(w) > 4 else w


def _words(text: str) -> set[str]:
    """Content words (no stopwords, at least 3 letters)."""
    return {_fold(w) for w in WORD_RE.findall(text or "") if len(w) >= 3 and w.lower() not in STOPWORDS}


def _contains(text: str, word: str) -> bool:
    """Whole-word, case-insensitive match."""
    return re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text or "", re.I) is not None


def identity_text(name: str, category: str = "", services: list[str] | None = None, website: str = "", description: str = "") -> str:
    """Everything that says what the business is, as one string."""
    host = (urlsplit(website).hostname or "") if website else ""
    domain_words = " ".join(part for part in re.split(r"[.\-]", host) if part not in {"www", "com", "in", "co", "net", "org"})
    return " ".join([name, category, " ".join(services or []), domain_words, description])


def proper_nouns(text: str) -> list[str]:
    """Capitalised words and acronyms that are not just the first word of a sentence."""
    found: list[str] = []
    for sentence in re.split(r"(?<=[.!?:])\s+", text or ""):
        words = WORD_RE.findall(sentence)
        for index, word in enumerate(words):
            if index == 0 and not word.isupper():
                continue
            if word[0].isupper() and word.lower() not in GENERIC_PROPER and word.lower() not in STOPWORDS:
                found.append(word)
    return found


def foreign_brands(claim: str, core: str, context: list[str], pages: list[str]) -> tuple[str, ...]:
    """Brand-like words in `claim` that are not part of the business (see the module docstring)."""
    core_words = _words(core)
    lower_corpus = " ".join(context + pages)
    out: list[str] = []
    for noun in proper_nouns(claim):
        if _fold(noun) in core_words:
            continue
        if re.search(rf"(?<![A-Za-z]){re.escape(noun.lower())}(?![A-Za-z])", lower_corpus):  # used as an ordinary word
            continue
        if sum(1 for page in pages if _contains(page, noun)) >= 2:  # on several pages: the advertiser's own name or product
            continue
        if noun not in out:
            out.append(noun)
    return tuple(out)


def check_relevance(claim: str, core: str, context: list[str] | None = None, pages: list[str] | None = None) -> Relevance:
    """Is `claim` about the business? `core` = name/category/domain/title; `context` = services and description; `pages` = page texts."""
    context, pages = list(context or []), list(pages or [])
    if not claim.strip():
        return Relevance(True)
    foreign = foreign_brands(claim, core, context, pages)
    if not foreign:
        return Relevance(True)
    clean_context = " ".join(text for text in context if not any(_contains(text, brand) for brand in foreign))
    claim_words = _words(claim) - {_fold(brand) for brand in foreign}
    overlap = claim_words & _words(core + " " + clean_context)
    if not overlap:
        return Relevance(False, f"it mentions {', '.join(foreign[:3])}, which is not part of this business", foreign)
    if len(foreign) >= 3 and len(overlap) <= 1:
        return Relevance(False, f"it is mostly about {', '.join(foreign[:3])}", foreign)
    return Relevance(True, foreign=foreign)
