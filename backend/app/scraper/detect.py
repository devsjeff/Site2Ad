"""Page classification: empty JavaScript shell? bot-protection page? parked domain? embedded app data?"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup, NavigableString

# ---- CSR scoring (SCRAPE.md 3.1). A score of 3 or more means "use the browser".
CSR_SCORE_THRESHOLD = 3
MIN_VISIBLE_TEXT_CHARS = 200
MIN_LINK_COUNT = 3
APP_ROOT_IDS = ("root", "app", "__next", "__nuxt")
HIDDEN_TEXT_TAGS = {"script", "style", "noscript", "template", "head", "title", "meta", "svg", "iframe"}
JS_REQUIRED_PHRASES = (
    "enable javascript", "javascript enabled", "javascript is disabled", "turn on javascript",
    "javascript to run this app", "requires javascript", "javascript is required", "you need to enable javascript",
)
GENERIC_TITLES = {
    "", "react app", "vite app", "vite + react", "vite + react + ts", "vue app", "vite + vue", "document",
    "loading", "loading...", "home", "untitled", "index", "next.js", "create next app",
}

PARKED_PHRASES = (
    "this domain is for sale", "domain is for sale", "buy this domain", "domain parking", "this domain may be for sale",
    "this web page is parked", "domain has expired", "this site can't be reached", "default web server page",
    "welcome to nginx", "apache2 ubuntu default page", "it works!", "index of /", "website is under construction",
    "site is under construction", "coming soon", "under maintenance", "account suspended",
)


def parse_html(html: str) -> BeautifulSoup:
    """Parse HTML with lxml when installed (fast), otherwise with the stdlib parser."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def visible_text(soup: BeautifulSoup) -> str:
    """Text a visitor would see: no scripts, styles, comments, <head>, or hidden templates."""
    pieces: list[str] = []
    for text in soup.find_all(string=True):
        if type(text) is not NavigableString:  # skips Comment, CData, Doctype, Script, Stylesheet...
            continue
        parent = text.parent
        if parent is not None and parent.name in HIDDEN_TEXT_TAGS:
            continue
        stripped = text.strip()
        if stripped:
            pieces.append(stripped)
    return " ".join(pieces)


def _page_title(soup: BeautifulSoup) -> str:
    """Return the <title> text or an empty string."""
    return soup.title.get_text(strip=True) if soup.title else ""


def has_empty_app_root(soup: BeautifulSoup) -> bool:
    """True when a React/Vue/Next mount point such as #root exists but holds no text."""
    for root_id in APP_ROOT_IDS:
        root = soup.find(id=root_id)
        if root is not None and not root.get_text(strip=True) and not root.find(["img", "a", "video", "picture"]):
            return True
    return False


def asks_to_enable_javascript(soup: BeautifulSoup) -> bool:
    """True when a <noscript> block tells the visitor to turn on JavaScript."""
    for noscript in soup.find_all("noscript"):
        text = noscript.get_text(" ", strip=True).lower()
        if any(phrase in text for phrase in JS_REQUIRED_PHRASES):
            return True
    return False


def score_csr(soup: BeautifulSoup, text: Optional[str] = None) -> tuple[int, list[str]]:
    """Score how likely the HTML is an empty JavaScript shell. Returns (score, reasons)."""
    score = 0
    reasons: list[str] = []
    text = visible_text(soup) if text is None else text
    if len(text) < MIN_VISIBLE_TEXT_CHARS:
        score += 2
        reasons.append("little_visible_text")
    if len(soup.find_all("a", href=True)) < MIN_LINK_COUNT:
        score += 2
        reasons.append("few_links")
    if has_empty_app_root(soup):
        score += 3
        reasons.append("empty_app_root")
    if asks_to_enable_javascript(soup):
        score += 3
        reasons.append("noscript_enable_js")
    if _page_title(soup).strip().lower() in GENERIC_TITLES:
        score += 1
        reasons.append("generic_title")
    return score, reasons


# ---------------------------------------------------------------- parked / placeholder pages


def looks_parked(text: str) -> bool:
    """True for parked, default-server or under-construction pages that carry no real business content."""
    lowered = text.lower()
    if len(lowered) > 800:
        return False
    return any(phrase in lowered for phrase in PARKED_PHRASES)


# ---------------------------------------------------------------- bot protection (detect only, never bypass)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
CLOUDFLARE_MARKERS = (
    "/cdn-cgi/challenge-platform", "cf-browser-verification", "_cf_chl_opt", "cf_chl_", "challenge-error-text",
    "checking your browser before accessing", "enable javascript and cookies to continue", "cf-error-details",
    "sorry, you have been blocked",
)
CAPTCHA_TITLE_HINTS = (
    "captcha", "are you a robot", "are you human", "verify you are human", "robot check", "human verification",
    "security check", "access denied", "request blocked", "pardon our interruption", "unusual traffic",
)
CAPTCHA_BODY_MARKERS = ("g-recaptcha", "h-captcha", "hcaptcha.com", "cf-turnstile", "px-captcha", "geo.captcha-delivery.com")


def detect_bot_protection(status: int, headers: dict[str, str], html: str, visible_len: Optional[int] = None) -> Optional[str]:
    """Return a label ('cloudflare', 'captcha', 'datadome', ...) only when we were actually challenged or blocked.

    `server: cloudflare` or a `cf-ray` header alone are NOT a block: most Cloudflare sites serve normally.
    """
    head = html[:300_000].lower()
    title_match = _TITLE_RE.search(html[:50_000])
    title = re.sub(r"\s+", " ", title_match.group(1)).strip().lower() if title_match else ""
    if visible_len is None:
        visible_len = len(re.sub(r"<[^>]+>", " ", head))
    thin = visible_len < 600

    if headers.get("cf-mitigated", "").lower() == "challenge":
        return "cloudflare"
    if title in {"just a moment...", "attention required! | cloudflare"} or (
        "just a moment" in title and any(m in head for m in CLOUDFLARE_MARKERS)
    ):
        return "cloudflare"
    if any(m in head for m in CLOUDFLARE_MARKERS) and (status in (403, 429, 503) or thin):
        return "cloudflare"
    if "datadome" in head and (status in (403, 429) or thin) or "x-datadome" in headers or headers.get("server", "").lower() == "datadome":
        return "datadome"
    if ("perimeterx" in head or "_pxhd" in head or "px-captcha" in head or "press & hold" in head) and (status in (403, 429) or thin):
        return "perimeterx"
    if ("incapsula incident id" in head or "_incapsula_resource" in head) and (status in (403, 503) or thin):
        return "incapsula"
    if "errors.edgesuite.net" in head or ("access denied" in head and "reference #" in head):
        return "akamai"
    if "sucuri website firewall" in head and (status == 403 or thin):
        return "sucuri"
    if any(hint in title for hint in CAPTCHA_TITLE_HINTS) and thin:
        return "captcha"
    if thin and any(m in head for m in CAPTCHA_BODY_MARKERS) and visible_len < 300:
        return "captcha"
    if status in (401, 403, 429):
        return f"http_{status}"
    return None


# ---------------------------------------------------------------- embedded app data (cheaper than a browser)

IMAGE_URL_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|avif)(?:[?#].*)?$", re.I)
_STATE_ASSIGN_RE = re.compile(
    r"window\s*\.\s*(__NUXT__|__INITIAL_STATE__|__PRELOADED_STATE__|__APOLLO_STATE__|__REDUX_STATE__)\s*=\s*", re.I
)
TITLE_KEYS = ("seotitle", "sitename", "site_name", "title", "name", "headline", "heading")
DESC_KEYS = ("metadescription", "seodescription", "description", "tagline", "subtitle", "about", "summary")


@dataclass
class EmbeddedData:
    """Useful facts pulled from server-embedded JSON (Next.js, Nuxt, initial-state blobs)."""

    sources: list[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    texts: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)

    @property
    def text_length(self) -> int:
        """Total characters of human-readable text found."""
        return sum(len(t) for t in self.texts)

    @property
    def is_sufficient(self) -> bool:
        """True when this data alone is enough to describe the business, so a browser is not needed."""
        return self.text_length >= MIN_VISIBLE_TEXT_CHARS and (bool(self.images) or len(self.links) >= 3 or bool(self.title))


def _balanced_json(text: str, start: int) -> Optional[str]:
    """Return the balanced {...} or [...] literal starting at `start`, or None."""
    if start >= len(text) or text[start] not in "{[":
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, min(len(text), start + 3_000_000)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _looks_like_prose(value: str) -> bool:
    """True for strings that read like human text rather than ids, urls, css or code."""
    if not (15 <= len(value) <= 800) or value.count(" ") < 2:
        return False
    if re.search(r"[{}<>;=]|function\s*\(|https?://|\\u00", value):
        return False
    letters = sum(c.isalpha() for c in value)
    return letters / len(value) > 0.6


def _walk(node: Any, out: EmbeddedData, depth: int = 0, key: str = "") -> None:
    """Collect text, images and links from a JSON tree (depth and size limited)."""
    if depth > 14 or len(out.texts) > 400:
        return
    if isinstance(node, dict):
        for k, v in list(node.items())[:200]:
            _walk(v, out, depth + 1, str(k).lower())
    elif isinstance(node, list):
        for v in node[:300]:
            _walk(v, out, depth + 1, key)
    elif isinstance(node, str):
        value = node.strip()
        if not value:
            return
        if IMAGE_URL_RE.search(value) and (value.startswith(("http://", "https://", "/", "//"))):
            if value not in out.images:
                out.images.append(value)
        elif key in {"href", "url", "path", "link", "slug"} and value.startswith(("/", "http")) and len(value) < 200:
            if value not in out.links and not IMAGE_URL_RE.search(value):
                out.links.append(value)
        elif _looks_like_prose(value):
            if value not in out.texts:
                out.texts.append(value)
            if not out.title and key in TITLE_KEYS and len(value) <= 120:
                out.title = value
            if not out.description and key in DESC_KEYS:
                out.description = value[:300]
        elif not out.title and ((key in TITLE_KEYS and 2 < len(value) <= 80) or key in {"sitename", "site_name"}):
            out.title = value


def extract_embedded_data(html: str) -> EmbeddedData:
    """Read __NEXT_DATA__, __NUXT_DATA__, window.__NUXT__ / __INITIAL_STATE__ style blobs, if present."""
    out = EmbeddedData()
    for script_id, label in (("__NEXT_DATA__", "__NEXT_DATA__"), ("__NUXT_DATA__", "__NUXT__")):
        match = re.search(
            r'<script[^>]*\bid=["\']' + script_id + r'["\'][^>]*>(.*?)</script>', html, re.I | re.S
        )
        if match:
            try:
                _walk(json.loads(match.group(1)), out)
                out.sources.append(label)
            except (ValueError, RecursionError):
                continue
    for match in _STATE_ASSIGN_RE.finditer(html[:4_000_000]):
        literal = _balanced_json(html, match.end())
        if not literal:
            continue
        try:
            _walk(json.loads(literal), out)
            out.sources.append("window." + match.group(1))
        except (ValueError, RecursionError):
            continue  # JS object literals that are not valid JSON are skipped, not guessed at
    out.texts = out.texts[:60]
    out.images = out.images[:40]
    out.links = out.links[:60]
    return out
