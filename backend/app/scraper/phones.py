"""Phone number extraction and normalisation (E.164). Uses `phonenumbers` when installed, a strict regex otherwise."""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from ..schemas import Phone, PhoneSource

try:  # optional dependency: much better coverage of international formats
    import phonenumbers  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised in environments without the package
    phonenumbers = None

DEFAULT_REGION = "IN"
SOURCE_PRIORITY: dict[str, int] = {
    "user": 0, "tel_link": 1, "whatsapp_link": 2, "json_ld": 3, "header": 4, "footer": 5, "contact_page": 6, "body": 7,
}

# A phone-looking run: optional +, digits separated by space . - ( ). Bounded so ids and GST numbers do not match.
_CANDIDATE = re.compile(r"(?<![\w@/.\-])(\+?\(?\d[\d\s().\-]{7,18}\d)(?![\w@])")
_LABEL_BEFORE = re.compile(r"(?:tel|phone|call|mobile|mob|whatsapp|contact|ph|cell|helpline|toll\s*free)[^\d+]{0,12}$", re.I)


def _digits(text: str) -> str:
    """Keep only digits."""
    return re.sub(r"\D", "", text)


def _plausible(digits: str) -> bool:
    """Reject obviously fake or non-phone digit strings (all same digit, simple sequences)."""
    if len(set(digits)) <= 2:
        return False
    return digits not in {"1234567890", "0123456789", "9876543210", "12345678901"}


def normalize_phone(raw: str, region: str = DEFAULT_REGION) -> Optional[str]:
    """Return an E.164 number for a raw phone string, or None when it does not look like a real number."""
    text = raw.strip()
    if not text:
        return None
    if phonenumbers is not None:
        try:
            parsed = phonenumbers.parse(text, region)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            return None
        except phonenumbers.NumberParseException:
            return None
    return _normalize_fallback(text, region)


def _normalize_fallback(text: str, region: str) -> Optional[str]:
    """Regex-based normalisation (India aware) used only when `phonenumbers` is missing."""
    has_plus = text.lstrip().startswith("+") or text.lstrip().startswith("00")
    digits = _digits(text)
    if text.lstrip().startswith("00"):
        digits = digits[2:]
    if not digits or not _plausible(digits):
        return None
    if has_plus:
        return f"+{digits}" if 8 <= len(digits) <= 15 else None
    if region != "IN":
        return None
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return f"+{digits}"
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 11 and digits[0] == "0" and digits[1] in "6789":
        return f"+91{digits[1:]}"
    if digits.startswith("1800") and 10 <= len(digits) <= 11:  # toll free
        return f"+91{digits}"
    if digits.startswith("0") and 10 <= len(digits) <= 11 and digits[1] in "2345":  # landline with STD code
        return f"+91{digits[1:]}"
    return None


def phone_from_link(href: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a tel:/WhatsApp link. Returns (e164, 'tel_link'|'whatsapp_link') or (None, None)."""
    href = href.strip()
    lowered = href.lower()
    if lowered.startswith("tel:"):
        number = normalize_phone(unquote(href[4:].split(";")[0].split("?")[0]))
        return (number, "tel_link") if number else (None, None)
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower()
    if host in {"wa.me", "www.wa.me"}:
        raw = parsed.path.strip("/")
    elif host.endswith("whatsapp.com") or lowered.startswith("whatsapp:"):
        raw = (parse_qs(parsed.query).get("phone") or [""])[0]
    else:
        return None, None
    digits = _digits(raw)
    if 8 <= len(digits) <= 15 and _plausible(digits):
        return f"+{digits}", "whatsapp_link"
    return None, None


def find_phones_in_text(text: str, source: PhoneSource, region: str = DEFAULT_REGION, limit: int = 6) -> list[Phone]:
    """Find phone numbers inside free text and label them with where they came from."""
    found: list[Phone] = []
    seen: set[str] = set()

    def add(number: Optional[str], shown: str) -> None:
        """Append a unique, valid number."""
        if number and number not in seen and len(found) < limit:
            seen.add(number)
            found.append(Phone(number=number, display=" ".join(shown.split())[:40], source=source))

    if phonenumbers is not None:
        for match in phonenumbers.PhoneNumberMatcher(text, region):
            try:
                add(phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164), match.raw_string)
            except Exception:
                continue
        return found

    for match in _CANDIDATE.finditer(text):
        raw = match.group(1)
        digits = _digits(raw)
        has_plus = raw.lstrip("( ").startswith("+")
        before = text[max(0, match.start() - 24): match.start()]
        labelled = bool(_LABEL_BEFORE.search(before))
        # Bare long digit runs (order ids, years, pincodes) only count when labelled or clearly an Indian mobile.
        if not has_plus and not labelled and not (len(digits) == 10 and digits[0] in "6789"):
            if not (digits.startswith("1800") or (digits.startswith("0") and len(digits) in (10, 11))):
                continue
        add(normalize_phone(raw, region), raw)
    return found


def merge_phones(groups: Iterable[Iterable[Phone]], limit: int = 8) -> list[Phone]:
    """Combine candidate lists, de-duplicate by number, and order by source reliability."""
    best: dict[str, Phone] = {}
    for group in groups:
        for phone in group:
            current = best.get(phone.number)
            if current is None or SOURCE_PRIORITY.get(phone.source, 9) < SOURCE_PRIORITY.get(current.source, 9):
                best[phone.number] = phone
    ordered = sorted(best.values(), key=lambda p: SOURCE_PRIORITY.get(p.source, 9))
    return ordered[:limit]
