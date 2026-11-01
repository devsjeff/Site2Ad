"""Numbers, prices and percentages in the video must exist in the product notes. These helpers find them and compare them."""

from __future__ import annotations

import re

# 4,000 | ₹4,000 | 15K+ | 10% | 45 MIN | 1,41,600 | 3.5x
FIGURE = re.compile(r"(?<![\w.])(?:[₹$€£]\s?)?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|[kKmM]\b|\+|x\b))?", re.I)
SMALL_WORDS = r"(?:step|steps|shot|ways?|things?|minutes?|minute|min|seconds?|second|sec|day|days|hour|hours|point|points|reasons?|tips?|simple)"


def figure_key(token: str) -> str:
    """The comparable form of a figure: digits without commas, plus % / k / + / x. '₹4,000' and '4000' are the same figure."""
    cleaned = token.lower().replace(",", "").replace(" ", "")
    cleaned = re.sub(r"^[₹$€£]", "", cleaned)
    return cleaned.rstrip(".")


def figures_in(text: str) -> list[str]:
    """Every figure in a text, as the user would read it."""
    return [m.group(0).strip() for m in FIGURE.finditer(text or "")]


def is_trivial(token: str) -> bool:
    """A single plain digit (1 to 9) such as 'in 3 steps' does not need a source: it counts the shots of the video itself."""
    return bool(re.fullmatch(r"[1-9]", token.strip()))


# Words that compare the product with others or promise the best: they need a claim that says so.
SUPERLATIVES = re.compile(
    r"\b(traditional|competitors?|competition|unlike|rivals?|alternatives?|better than|cheaper than|cheapest|best|#1|number one|"
    r"leading|leader|guaranteed?|unbeatable|only|fastest|biggest|largest|revolutionary|world.?class)\b", re.I)


def unsupported_words(text: str, allowed_text: str) -> list[str]:
    """Comparisons and superlatives in `text` that the cited claims do not use ('traditional', 'best', 'guaranteed'...)."""
    allowed = allowed_text.lower()
    return sorted({m.group(0).lower() for m in SUPERLATIVES.finditer(text or "") if m.group(0).lower() not in allowed})


STOP = {"with", "that", "this", "your", "from", "have", "will", "more", "than", "into", "each", "they", "them", "what", "when", "where", "which", "their",
        "then", "also", "just", "only", "every", "about", "over", "make", "makes", "made", "plus", "per", "are", "the", "and", "for", "you", "our", "its"}


def content_words(text: str) -> list[str]:
    """The meaningful words of a text (four letters or more, no filler words), lower case, plural 's' removed."""
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", text or "")
    return [stem(w.lower()) for w in words if w.lower() not in STOP]


def stem(word: str) -> str:
    """A light plural/verb ending removal so 'watches' matches 'watch' and 'passengers' matches 'passenger'."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes")) and len(word) > 5:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def grounded(text: str, source_text: str) -> float:
    """The share of the content words of `text` that appear in `source_text` (1.0 when the text has no content words)."""
    words = content_words(text)
    if not words:
        return 1.0
    have = set(content_words(source_text))
    return sum(1 for w in words if w in have) / len(words)


def missing_symbols(text: str, allowed_text: str) -> list[str]:
    """Figures written without the currency symbol the source gives them: on screen it must say '₹4,000', not '4000'."""
    symbols: dict[str, str] = {}
    for token in figures_in(allowed_text):
        match = re.match(r"([₹$€£])", token)
        if match:
            symbols.setdefault(figure_key(token), match.group(1))
    out = []
    for token in figures_in(text):
        key = figure_key(token)
        if key in symbols and not re.match(r"[₹$€£]", token) and not is_trivial(token):
            out.append(f"{token} (write {symbols[key]}{token})")
    return out


def restore_symbols(text: str, allowed_text: str) -> str:
    """Put back the currency symbol (and the comma grouping) the source gives a figure: 'from 4000 per cab' -> 'from ₹4,000 per cab'."""
    sourced: dict[str, str] = {}
    for token in figures_in(allowed_text):
        if re.match(r"[₹$€£]", token):
            sourced.setdefault(figure_key(token), token.replace(" ", ""))

    def fix(match: re.Match) -> str:
        token = match.group(0)
        key = figure_key(token)
        if key in sourced and not re.match(r"[₹$€£]", token.strip()) and not is_trivial(token):
            return (" " if token.startswith(" ") else "") + sourced[key]
        return token

    return FIGURE.sub(fix, text or "")


def speakable(text: str) -> str:
    """A line as a voice should read it: '₹4,000' -> '4,000 rupees', '$5' -> '5 dollars', '18%' -> '18 percent'."""
    names = {"₹": "rupees", "$": "dollars", "€": "euros", "£": "pounds"}
    text = re.sub(r"([₹$€£])\s?(\d[\d,]*(?:\.\d+)?)(?:\s?([kKmM])\b)?", lambda m: f"{m.group(2)}{m.group(3) or ''} {names[m.group(1)]}", text)
    text = re.sub(r"(\d)\s?%", r"\1 percent", text)
    return re.sub(r"\b(\d+)\s?[kK]\b", r"\1 thousand", text)


def unsupported_figures(text: str, allowed_text: str) -> list[str]:
    """Figures in `text` that do not appear in `allowed_text` (the notes and the page). Plain single digits are allowed."""
    allowed = {figure_key(token) for token in figures_in(allowed_text)}
    allowed_cores = {re.sub(r"[%+kmx]$", "", key) for key in allowed}
    missing: list[str] = []
    for token in figures_in(text):
        if is_trivial(token):
            continue
        key = figure_key(token)
        if key in allowed:
            continue
        # "15K" in the video is fine when the page says "15K+" (the same figure with a plus sign)
        if key.endswith("+") and key[:-1] in allowed or f"{key}+" in allowed:
            continue
        if key not in allowed_cores or re.search(r"[%kmx]$", key):
            missing.append(token)
    return missing
