"""Turn one HTML document into structured facts. Pure functions: no network, no I/O.

Metadata priority (SCRAPE.md 3.4), first value found wins per field:
JSON-LD -> Open Graph -> Twitter cards -> <title>/<meta> -> <h1>/<h2> -> <html lang>.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from ..schemas import Phone
from .detect import (
    EmbeddedData, GENERIC_TITLES, detect_bot_protection, extract_embedded_data, looks_parked, parse_html,
    score_csr, visible_text,
)
from .phones import find_phones_in_text, merge_phones, phone_from_link
from .safety import PATH_TENANT_HOSTS, is_media_url

TEXT_EXCERPT_HOME = 2500
TEXT_EXCERPT_PAGE = 1200
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src"}
SOCIAL_HOSTS = (
    "instagram.com", "facebook.com", "fb.com", "youtube.com", "youtu.be", "linkedin.com", "twitter.com", "x.com",
    "pinterest.com", "tiktok.com", "t.me", "linktr.ee", "maps.google.com", "goo.gl", "g.page", "maps.app.goo.gl",
)
SKIP_ANCESTORS = ["nav", "footer", "header", "aside", "form", "noscript", "script", "style", "template", "svg"]
HERO_HINT = re.compile(r"hero|banner|slider|carousel|cover|featured|jumbotron|masthead|splash|main-image|header-img", re.I)
BAD_IMAGE_HINT = re.compile(
    r"logo|icon|avatar|sprite|pixel|tracking|badge|payment|flag|emoji|spinner|loader|placeholder|blank|spacer|1x1|"
    r"gravatar|captcha|arrow|button|rating|star|social|share|qr[-_]?code|favicon|thumb(?:nail)?-?(?:xs|sm)",
    re.I,
)
LAZY_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-lazy", "data-image", "data-full", "data-large", "src")
GENERIC_SERVICE_WORDS = {
    "read more", "learn more", "view all", "see all", "know more", "click here", "get started", "contact us", "more",
    "view more", "explore", "book now", "enquire now", "details", "shop now", "home", "about us", "services", "products",
}
OFFER_RE = re.compile(
    r"(\b\d{1,2}\s?%\s?(?:off|discount|cashback)\b|\b(?:flat|upto|up to|save)\s+(?:rs\.?|₹|\$|€|£)?\s?\d+\s?%?\s?(?:off)?\b"
    r"|\bbuy\s+\d+\s+get\s+\d+\b|\bfree\s+(?:delivery|shipping|consultation|trial|demo|installation|checkup|check-up|quote|estimate)\b"
    r"|\bspecial offer\b|\blimited[- ]time\b|\bfestive offer\b|\bcashback\b|\bcombo offer\b|\bearly[- ]bird\b"
    r"|\bstarting (?:at|from) (?:rs\.?|₹|\$|€|£)\s?\d+)",
    re.I,
)
CTA_RE = re.compile(
    r"^(book|call|contact|order|shop|buy|get|enquire|inquire|reserve|visit|request|schedule|start|try|join|"
    r"sign up|learn more|view menu|explore|download|whatsapp|check|find|apply|register|rent|hire)\b",
    re.I,
)
STREET_WORDS = re.compile(r"\b(road|rd\.?|street|st\.?|nagar|sector|floor|plot|near|opp\.?|opposite|chowk|marg|lane|colony|avenue|ave\.?|market|complex|tower|building|bldg)\b", re.I)
PIN_RE = re.compile(r"\b[1-9]\d{5}\b")
BUSINESS_SUFFIXES = ("business", "store", "restaurant", "shop", "hotel", "clinic", "salon", "service", "center", "centre", "agency", "school", "gym", "spa", "bakery", "cafe", "dealer")
BUSINESS_TYPES = {
    "localbusiness", "organization", "corporation", "ngo", "educationalorganization", "medicalorganization", "sportsteam",
    "foodestablishment", "lodgingbusiness", "store", "professionalservice", "homeandconstructionbusiness", "website",
}


@dataclass
class LinkInfo:
    """A same-site link with its anchor text and where on the page it was found."""

    url: str
    label: str = ""
    zone: str = "body"  # nav | footer | body


@dataclass
class Extraction:
    """Everything we learn from one document."""

    title: str = ""
    description: str = ""
    language: str = ""
    name: str = ""
    logo: str = ""
    logo_source: str = ""
    favicon: str = ""
    images: list[str] = field(default_factory=list)
    phones: list[Phone] = field(default_factory=list)
    whatsapp: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    social: list[str] = field(default_factory=list)
    address: str = ""
    category: str = ""
    services: list[str] = field(default_factory=list)
    offer: str = ""
    cta: str = ""
    brand_colors: list[str] = field(default_factory=list)
    text_excerpt: str = ""
    links: list[LinkInfo] = field(default_factory=list)
    keywords: str = ""
    # diagnostics
    csr_score: int = 0
    csr_reasons: list[str] = field(default_factory=list)
    visible_len: int = 0
    bot_protection: Optional[str] = None
    parked: bool = False
    embedded: EmbeddedData = field(default_factory=EmbeddedData)
    has_json_ld: bool = False


# --------------------------------------------------------------------------- small helpers


def clean(text: Optional[str], limit: int = 0) -> str:
    """Collapse whitespace, unescape entities, and optionally cut to `limit` characters."""
    if not text:
        return ""
    value = " ".join(html_lib.unescape(str(text)).split())
    return value[:limit].rstrip() if limit else value


def host_key(url_or_host: str) -> str:
    """Hostname without a leading www., lower case."""
    host = urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_same_site(url: str, home_url: str) -> bool:
    """True when url is on the same site as home_url (www-insensitive; tenant path aware)."""
    parsed, home = urlparse(url), urlparse(home_url)
    if host_key(url) != host_key(home_url):
        return False
    for tenant_host in PATH_TENANT_HOSTS:
        if host_key(home_url) == tenant_host or host_key(home_url).endswith("." + tenant_host):
            return parsed.path.startswith(home.path.rstrip("/") + "/") or parsed.path.rstrip("/") == home.path.rstrip("/")
    return True


def normalize_link(href: Optional[str], base_url: str) -> Optional[str]:
    """Make a link absolute and tidy; None for non-page links (anchors, javascript:, mailto:, files)."""
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "sms:", "data:", "whatsapp:", "blob:")):
        return None
    try:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if is_media_url(parsed.path):
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query) if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS])
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", "", query, ""))


def _meta_map(soup: BeautifulSoup) -> dict[str, str]:
    """Map lower-cased meta name/property/itemprop to content (first value wins)."""
    out: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        content = tag.get("content")
        if not content:
            continue
        for attr in ("property", "name", "itemprop", "http-equiv"):
            key = tag.get(attr)
            if key:
                out.setdefault(str(key).lower(), clean(content))
    return out


# --------------------------------------------------------------------------- JSON-LD


def _walk_jsonld(node: Any, out: list[dict], depth: int = 0) -> None:
    """Flatten JSON-LD (arrays and @graph) into a list of typed dict nodes."""
    if depth > 6:
        return
    if isinstance(node, list):
        for item in node[:100]:
            _walk_jsonld(item, out, depth + 1)
    elif isinstance(node, dict):
        if "@type" in node:
            out.append(node)
        for key in ("@graph", "mainEntity", "publisher", "provider", "about"):
            if key in node:
                _walk_jsonld(node[key], out, depth + 1)


def parse_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Return all typed JSON-LD nodes on the page; invalid blocks are skipped."""
    nodes: list[dict] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = (script.string or script.get_text() or "").strip()
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw).strip()
        if not raw:
            continue
        try:
            _walk_jsonld(json.loads(raw, strict=False), nodes)
        except (ValueError, RecursionError):
            continue
    return nodes


def _types(node: dict) -> list[str]:
    """Lower-cased @type values of a node."""
    value = node.get("@type")
    values = value if isinstance(value, list) else [value]
    return [str(v).lower().split("/")[-1].split(":")[-1] for v in values if v]


def _business_node(nodes: list[dict]) -> Optional[dict]:
    """Pick the most business-like node: LocalBusiness family, then Organization, then WebSite."""
    def rank(node: dict) -> int:
        """Lower is better."""
        types = _types(node)
        if any(t.endswith(BUSINESS_SUFFIXES) and t != "organization" for t in types):
            return 0
        if "localbusiness" in types:
            return 0
        if any(t in {"organization", "corporation", "ngo", "educationalorganization", "medicalorganization"} for t in types):
            return 1
        if "website" in types:
            return 2
        return 9

    ranked = sorted((n for n in nodes if rank(n) < 9), key=rank)
    return ranked[0] if ranked else None


def _ld_text(value: Any) -> str:
    """First usable string inside a JSON-LD value (str, dict with name/url, or list)."""
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        return clean(value.get("url") or value.get("name") or value.get("@id") or "")
    if isinstance(value, list):
        for item in value:
            text = _ld_text(item)
            if text:
                return text
    return ""


def _ld_address(value: Any) -> str:
    """Flatten a PostalAddress (or string) into one line."""
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return clean(value, 220)
    if isinstance(value, dict):
        parts = [value.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
        flat = ", ".join(clean(p if isinstance(p, str) else _ld_text(p)) for p in parts if p)
        return clean(flat, 220)
    return ""


def _ld_services(node: dict) -> list[str]:
    """Names of offered services/products from makesOffer / hasOfferCatalog."""
    names: list[str] = []

    def add(value: Any, depth: int = 0) -> None:
        """Collect names from nested offers and catalogs."""
        if depth > 4:
            return
        if isinstance(value, list):
            for item in value[:30]:
                add(item, depth + 1)
        elif isinstance(value, dict):
            for key in ("itemOffered", "item"):
                if key in value:
                    add(value[key], depth + 1)
            name = value.get("name")
            if isinstance(name, str) and 2 < len(name) <= 60:
                names.append(clean(name))
            for key in ("itemListElement", "hasOfferCatalog", "makesOffer", "offers"):
                if key in value:
                    add(value[key], depth + 1)

    for key in ("makesOffer", "hasOfferCatalog", "offers"):
        if key in node:
            add(node[key])
    cuisine = node.get("servesCuisine")
    if isinstance(cuisine, str):
        names.append(clean(cuisine, 60))
    elif isinstance(cuisine, list):
        names.extend(clean(c, 60) for c in cuisine[:5] if isinstance(c, str))
    return names


# --------------------------------------------------------------------------- names, text


def site_name_from_title(title: str, host: str) -> str:
    """Guess the business name from a page title like 'Home | Sharma Sweets' using the domain as a hint."""
    if not title:
        return ""
    parts = [p.strip() for p in re.split(r"\s+[|\-–—:•·»]\s+|\s*\|\s*", title) if p.strip()]
    if not parts:
        return clean(title, 80)
    domain_letters = re.sub(r"[^a-z0-9]", "", host_key(host).split(".")[0]) if host else ""
    generic = {"home", "homepage", "welcome", "official website", "official site", "index", "website"}
    best = ""
    for part in parts:
        letters = re.sub(r"[^a-z0-9]", "", part.lower())
        if part.lower() in generic or not letters:
            continue
        if domain_letters and (letters in domain_letters or domain_letters in letters):
            return clean(part, 80)
        if not best:
            best = part
    return clean(best or parts[0], 80)


def _first_paragraph(soup: BeautifulSoup) -> str:
    """First sentence-like paragraph of at least 60 characters outside nav/footer/header."""
    for p in soup.find_all("p"):
        if p.find_parent(SKIP_ANCESTORS):
            continue
        text = clean(p.get_text(" ", strip=True))
        if len(text) >= 60:
            return clean(text, 300)
    return ""


def build_text_excerpt(soup: BeautifulSoup, limit: int) -> str:
    """Readable text of the main content: headings, paragraphs, list items; no nav/footer/forms/scripts."""
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    lines: list[str] = []
    seen: set[str] = set()
    total = 0
    for element in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "figcaption", "dd", "td"]):
        if element.find_parent(SKIP_ANCESTORS):
            continue
        text = clean(element.get_text(" ", strip=True))
        if len(text) < 3 or text.lower() in seen:
            continue
        seen.add(text.lower())
        lines.append(text)
        total += len(text) + 1
        if total >= limit:
            break
    return clean(" ".join(lines), limit) if lines else ""


# --------------------------------------------------------------------------- images


def _largest_srcset(srcset: str) -> str:
    """Pick the widest URL in a srcset value."""
    best_url, best_width = "", -1
    for part in srcset.split(","):
        pieces = part.strip().split()
        if not pieces:
            continue
        width = 0
        if len(pieces) > 1:
            descriptor = pieces[1]
            if descriptor.endswith("w") and descriptor[:-1].isdigit():
                width = int(descriptor[:-1])
            elif descriptor.endswith("x"):
                try:
                    width = int(float(descriptor[:-1]) * 1000)
                except ValueError:
                    width = 0
        if width > best_width:
            best_width, best_url = width, pieces[0]
    return best_url


def _int_attr(tag: Tag, name: str) -> int:
    """Read a numeric attribute like width='640' or width='640px'; 0 when absent."""
    raw = str(tag.get(name) or "")
    match = re.match(r"\s*(\d+)", raw)
    return int(match.group(1)) if match else 0


def _image_ok(url: str) -> bool:
    """Reject data URIs, svg/ico (logos and icons) and non-image extensions."""
    lowered = url.lower().split("?")[0].split("#")[0]
    if lowered.startswith(("data:", "javascript:", "blob:")):
        return False
    if lowered.endswith((".svg", ".ico", ".css", ".js", ".html", ".php", ".json", ".mp4", ".webm", ".pdf")):
        return False
    return True


def extract_images(soup: BeautifulSoup, page_url: str, jsonld_images: list[str], meta: dict[str, str], limit: int, min_px: int) -> list[str]:
    """Rank main-page images (URLs only, nothing is downloaded). og:image first, then JSON-LD, then hero-like <img>s."""
    scored: dict[str, tuple[float, str]] = {}  # dedupe key -> (score, url)

    def add(raw: Optional[str], score: float) -> None:
        """Register a candidate, keeping the best score per distinct image path."""
        if not raw:
            return
        raw = raw.strip()
        if not raw or not _image_ok(raw):
            return
        absolute = urljoin(page_url, raw)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return
        key = parsed.netloc.lower() + parsed.path
        if key not in scored or scored[key][0] < score:
            scored[key] = (score, absolute)

    add(meta.get("og:image") or meta.get("og:image:url") or meta.get("og:image:secure_url"), 100)
    for url in jsonld_images[:4]:
        add(url, 70)
    add(meta.get("twitter:image") or meta.get("twitter:image:src"), 60)

    for order, img in enumerate(soup.find_all("img")):
        hint_text = " ".join(str(v) for v in (img.get("class") or [])) + " " + str(img.get("id") or "") + " " + str(img.get("alt") or "")
        raw = ""
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            raw = _largest_srcset(str(srcset))
        if not raw:
            for attr in LAZY_ATTRS:
                value = img.get(attr)
                if value and not str(value).startswith("data:"):
                    raw = str(value)
                    break
        if not raw:
            continue
        width, height = _int_attr(img, "width"), _int_attr(img, "height")
        if (width and width < min_px) or (height and height < min_px):
            continue
        if BAD_IMAGE_HINT.search(raw) or BAD_IMAGE_HINT.search(hint_text):
            continue
        score = 10.0 + min(width, 1600) / 100 + max(0.0, (40 - order)) / 8
        if HERO_HINT.search(hint_text) or HERO_HINT.search(raw):
            score += 25
        if img.find_parent(["footer", "nav"]):
            score -= 18
        if img.find_parent(["header"]):
            score -= 4
        if img.find_parent(["main", "section", "article"]):
            score += 4
        add(raw, score)
    for source in soup.find_all("source"):
        srcset = source.get("srcset") or source.get("data-srcset")
        if srcset and source.find_parent("picture") is not None:
            add(_largest_srcset(str(srcset)), 14)
    for tag in soup.find_all(style=re.compile(r"background(-image)?\s*:[^;]*url\(", re.I)):
        match = re.search(r"url\(\s*['\"]?([^'\")]+)", str(tag.get("style")))
        if match and not BAD_IMAGE_HINT.search(match.group(1)):
            hint_text = " ".join(str(v) for v in (tag.get("class") or [])) + " " + str(tag.get("id") or "")
            add(match.group(1), 30 + (25 if HERO_HINT.search(hint_text) else 0))
    ranked = sorted(scored.values(), key=lambda item: -item[0])
    return [url for _, url in ranked[:limit]]


# --------------------------------------------------------------------------- logo, favicon, colours


def _logo_and_favicon(soup: BeautifulSoup, page_url: str, meta: dict[str, str], ld_logo: str) -> tuple[str, str, str]:
    """Return (logo_url, logo_source, favicon_url)."""
    logo, source = "", ""
    if ld_logo:
        logo, source = urljoin(page_url, ld_logo), "json_ld"
    if not logo:
        scope = soup.find(["header", "nav"]) or soup
        for img in scope.find_all("img"):
            hint = " ".join([str(img.get("alt") or ""), " ".join(img.get("class") or []), str(img.get("id") or ""), str(img.get("src") or ""), str(img.get("data-src") or "")])
            parent = img.find_parent("a")
            parent_hint = " ".join((parent.get("class") or []) + [str(parent.get("id") or "")]) if parent else ""
            if "logo" in hint.lower() or "logo" in parent_hint.lower():
                raw = str(img.get("src") or img.get("data-src") or "")
                if not raw and img.get("srcset"):
                    raw = _largest_srcset(str(img.get("srcset")))
                if raw and not raw.startswith("data:"):
                    logo, source = urljoin(page_url, raw), "header_img"
                    break
    if not logo and meta.get("og:image"):
        logo, source = urljoin(page_url, meta["og:image"]), "og_image"

    favicon, best = "", -1
    for link in soup.find_all("link", rel=True, href=True):
        rels = " ".join(link.get("rel") if isinstance(link.get("rel"), list) else [str(link.get("rel"))]).lower()
        if "icon" not in rels:
            continue
        size_match = re.match(r"(\d+)x", str(link.get("sizes") or ""))
        size = int(size_match.group(1)) if size_match else 0
        rank = size + (1000 if "apple-touch-icon" in rels else 0)
        if rank > best:
            best, favicon = rank, urljoin(page_url, str(link["href"]))
    if not favicon:
        parsed = urlparse(page_url)
        favicon = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    return logo, source, favicon


def _hex(color: str) -> Optional[str]:
    """Normalise #rgb / #rrggbb / rgb(r,g,b) to '#rrggbb'; None if not a colour."""
    color = color.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", color):
        return "#" + "".join(ch * 2 for ch in color[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", color):
        return color
    match = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", color)
    if match:
        r, g, b = (min(255, int(v)) for v in match.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _is_neutral(hex_color: str) -> bool:
    """True for white, black and greys (not interesting brand colours)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return max(r, g, b) - min(r, g, b) < 18


def extract_brand_colors(soup: BeautifulSoup, meta: dict[str, str]) -> list[str]:
    """theme-color first, then CSS brand variables, then the most used non-grey colours in inline CSS."""
    colors: list[str] = []

    def add(value: Optional[str]) -> None:
        """Append a normalised, non-neutral colour once."""
        normal = _hex(value) if value else None
        if normal and normal not in colors and not _is_neutral(normal):
            colors.append(normal)

    add(meta.get("theme-color"))
    add(meta.get("msapplication-tilecolor"))
    css = " ".join(style.get_text() for style in soup.find_all("style"))[:200_000]
    for match in re.finditer(r"--(?:primary|brand|accent|main|theme|secondary)[\w-]*\s*:\s*(#[0-9a-fA-F]{3,6}|rgba?\([^)]+\))", css):
        add(match.group(1))
    inline = css + " " + " ".join(str(t.get("style")) for t in soup.find_all(style=True)[:300])
    counts = Counter(_hex(m) for m in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", inline))
    for color, _ in counts.most_common(12):
        if color:
            add(color)
        if len(colors) >= 4:
            break
    return colors[:4]


# --------------------------------------------------------------------------- facts: address, services, offer, cta


def extract_address(soup: BeautifulSoup, ld_address: str) -> str:
    """JSON-LD address, then microdata, then <address>, then a footer line with a PIN code and street words."""
    if ld_address:
        return ld_address
    parts = [clean(t.get_text(" ", strip=True)) for t in soup.find_all(attrs={"itemprop": re.compile(r"^(streetAddress|addressLocality|addressRegion|postalCode)$")})]
    if parts:
        return clean(", ".join(p for p in parts if p), 220)
    tag = soup.find("address")
    if tag:
        text = clean(tag.get_text(" ", strip=True), 220)
        if 10 <= len(text) <= 220:
            return text
    footer = soup.find("footer")
    if footer:
        for element in footer.find_all(["p", "li", "div", "span"]):
            if element.find(["p", "li", "div"]):
                continue
            text = clean(element.get_text(" ", strip=True))
            if 15 <= len(text) <= 200 and PIN_RE.search(text) and STREET_WORDS.search(text):
                return text
    return ""


def extract_services(soup: BeautifulSoup, ld_services: list[str]) -> list[str]:
    """Services/products from JSON-LD, nav dropdowns labelled Services/Products, or 'Our services' style sections."""
    found: list[str] = []

    def add(text: str) -> None:
        """Keep short, non-generic, distinct service names."""
        value = clean(text, 60)
        words = value.split()
        if not (3 <= len(value) <= 60) or len(words) > 7 or value.lower() in GENERIC_SERVICE_WORDS:
            return
        if value.lower() in {s.lower() for s in found} or re.search(r"[.!?]$", value) and len(words) > 4:
            return
        found.append(value)

    for name in ld_services:
        add(name)
    heading_re = re.compile(r"\b(services?|products?|what we (?:do|offer)|solutions?|menu|specialit(?:y|ies)|treatments?|courses?|packages?|offerings?)\b", re.I)
    for li in soup.find_all("li"):
        label_tag = li.find("a", recursive=False)
        sub = li.find(["ul", "div"], recursive=False)
        if label_tag is not None and sub is not None and heading_re.search(label_tag.get_text(" ", strip=True)) and len(label_tag.get_text()) < 40:
            for a in sub.find_all("a")[:12]:
                add(a.get_text(" ", strip=True))
    for heading in soup.find_all(["h1", "h2", "h3"]):
        text = clean(heading.get_text(" ", strip=True))
        if len(text) > 50 or not heading_re.search(text):
            continue
        if heading.find_parent(["nav", "footer", "header"]):
            continue
        section = heading.find_parent(["section", "div"]) or heading.parent
        if section is None:
            continue
        for item in section.find_all(["h3", "h4", "li", "strong"], limit=40):
            if item is heading or item.find_parent(["nav", "footer"]):
                continue
            add(item.get_text(" ", strip=True))
        if len(found) >= 8:
            break
    return found[:8]


def extract_offer(soup: BeautifulSoup) -> str:
    """First short line that reads like a real offer (discount, free X, buy N get M); '' if none."""
    for element in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b", "p", "span", "a", "button", "div"], limit=1500):
        if element.find_parent(["script", "style", "noscript"]) or element.find(["div", "p", "section"]):
            continue
        text = clean(element.get_text(" ", strip=True))
        if 6 <= len(text) <= 120 and OFFER_RE.search(text):
            return text
    return ""


def extract_cta(soup: BeautifulSoup) -> str:
    """First button-like element whose text starts with an action verb (Book, Call, Order, ...)."""
    def candidates() -> Iterable[Tag]:
        """Buttons and button-styled links first, then any link."""
        for tag in soup.find_all(["button", "a"], limit=800):
            classes = " ".join(tag.get("class") or []).lower()
            if tag.name == "button" or "btn" in classes or "button" in classes or "cta" in classes:
                yield tag
        for tag in soup.find_all("a", limit=800):
            yield tag

    for tag in candidates():
        if tag.find_parent(["footer"]):
            continue
        text = clean(tag.get_text(" ", strip=True))
        if 3 <= len(text) <= 40 and CTA_RE.match(text):
            return text
    return ""


def _category_from_types(nodes: list[dict]) -> str:
    """Readable category from a specific JSON-LD @type such as Restaurant or DentalClinic."""
    generic = {"organization", "localbusiness", "website", "webpage", "corporation", "thing", "person", "breadcrumblist", "imageobject"}
    for node in nodes:
        values = node.get("@type")
        for raw in values if isinstance(values, list) else [values]:
            name = str(raw or "").split("/")[-1]
            if name.lower() not in generic and name.lower().endswith(BUSINESS_SUFFIXES + ("establishment",)):
                return clean(re.sub(r"(?<!^)(?=[A-Z])", " ", name), 40)
    return ""


# --------------------------------------------------------------------------- links


def _zone_of(anchor: Tag) -> str:
    """Classify where an anchor sits: footer, nav (header/menu), or body."""
    for parent in anchor.parents:
        name = getattr(parent, "name", None)
        if name is None or name in {"[document]", "html", "body"}:
            break
        if name == "footer":
            return "footer"
        if name in {"nav", "header"}:
            return "nav"
        role = str(parent.get("role") or "").lower()
        if role == "contentinfo":
            return "footer"
        if role in {"banner", "navigation"}:
            return "nav"
        marker = (" ".join(parent.get("class") or []) + " " + str(parent.get("id") or "")).lower()
        if re.search(r"\b(site-)?footer\b|footer-|-footer", marker):
            return "footer"
        if re.search(r"\b(site-)?header\b|navbar|nav-|-nav\b|\bmenu\b|main-menu|primary-menu", marker):
            return "nav"
    return "body"


def extract_links(soup: BeautifulSoup, page_url: str, home_url: str) -> tuple[list[LinkInfo], list[str], list[str], list[str], list[Phone]]:
    """Return (page links, whatsapp numbers, emails, social links, phones from tel:/wa links)."""
    links: dict[str, LinkInfo] = {}
    whatsapp: list[str] = []
    emails: list[str] = []
    social: list[str] = []
    phones: list[Phone] = []
    ordered: list[tuple[Tag, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        lowered = href.lower()
        if lowered.startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) and email not in emails:
                emails.append(email)
            continue
        number, source = phone_from_link(href)
        if number and source:
            phones.append(Phone(number=number, display=clean(anchor.get_text(" ", strip=True), 40), source=source))  # type: ignore[arg-type]
            if source == "whatsapp_link" and number not in whatsapp:
                whatsapp.append(number)
            continue
        absolute = normalize_link(href, page_url)
        if not absolute:
            continue
        host = host_key(absolute)
        if any(host == s or host.endswith("." + s) for s in SOCIAL_HOSTS):
            if absolute not in social and len(social) < 8:
                social.append(absolute)
            continue
        if not is_same_site(absolute, home_url):
            continue
        if absolute.rstrip("/") == home_url.rstrip("/"):
            continue
        ordered.append((anchor, absolute))
    for anchor, absolute in ordered:
        label = clean(anchor.get_text(" ", strip=True) or anchor.get("title") or anchor.get("aria-label") or "", 60)
        zone = _zone_of(anchor)
        existing = links.get(absolute)
        if existing is None:
            links[absolute] = LinkInfo(absolute, label, zone)
        else:
            if not existing.label and label:
                existing.label = label
            if existing.zone == "body" and zone != "body":
                existing.zone = zone
    result = list(links.values())
    if result and all(link.zone == "body" for link in result):
        # messy HTML with no header/nav/footer: first links act as the menu, last links as the footer
        for link in result[:12]:
            link.zone = "nav"
        for link in result[-12:]:
            if link.zone == "body":
                link.zone = "footer"
    return result, whatsapp, emails, social, phones


# --------------------------------------------------------------------------- orchestration for one document


def extract_page(
    html: str,
    page_url: str,
    home_url: str,
    *,
    max_images: int = 8,
    min_image_px: int = 50,
    status: int = 200,
    headers: Optional[dict[str, str]] = None,
    phone_source: str = "",
    excerpt_chars: int = TEXT_EXCERPT_HOME,
) -> Extraction:
    """Parse one HTML document and return everything useful from it (also CSR score and bot-check)."""
    soup = parse_html(html)
    text = visible_text(soup)
    out = Extraction(visible_len=len(text))
    out.csr_score, out.csr_reasons = score_csr(soup, text)
    out.bot_protection = detect_bot_protection(status, headers or {}, html, len(text))
    out.parked = looks_parked(text)
    out.embedded = extract_embedded_data(html) if ("__NEXT_DATA__" in html or "__NUXT" in html or "__INITIAL_STATE__" in html or "__PRELOADED_STATE__" in html or "__APOLLO_STATE__" in html) else EmbeddedData()

    meta = _meta_map(soup)
    nodes = parse_json_ld(soup)
    out.has_json_ld = bool(nodes)
    biz = _business_node(nodes) or {}
    host = urlparse(page_url).hostname or ""

    h1 = soup.find("h1")
    h1_text = clean(h1.get_text(" ", strip=True), 120) if h1 else ""
    h2 = soup.find("h2")
    h2_text = clean(h2.get_text(" ", strip=True), 120) if h2 else ""
    title_tag = clean(soup.title.get_text(" ", strip=True), 160) if soup.title else ""

    def real(value: str) -> str:
        """Drop framework default titles such as 'React App' or 'Create Next App'."""
        return "" if value.strip().lower() in GENERIC_TITLES else value

    og_title, title_tag = real(meta.get("og:title", "")), real(title_tag)
    out.title = og_title or real(meta.get("twitter:title", "")) or title_tag or h1_text or out.embedded.title
    out.name = (
        _ld_text(biz.get("name")) or meta.get("og:site_name")
        or site_name_from_title(title_tag or og_title, host) or out.embedded.title or h1_text
    )
    out.description = (
        _ld_text(biz.get("description")) or meta.get("og:description") or meta.get("twitter:description")
        or meta.get("description") or _first_paragraph(soup) or out.embedded.description or h2_text
    )
    out.keywords = meta.get("keywords", "")
    html_tag = soup.find("html")
    lang = (html_tag.get("lang") if html_tag else "") or meta.get("og:locale") or _ld_text(biz.get("inLanguage")) or meta.get("content-language", "")
    out.language = clean(str(lang), 12).replace("_", "-")

    ld_images: list[str] = []
    for node in nodes:
        for key in ("image", "photo"):
            value = node.get(key)
            candidates = value if isinstance(value, list) else [value]
            for item in candidates:
                text_value = _ld_text(item)
                if text_value and text_value.startswith(("http", "/")) and text_value not in ld_images:
                    ld_images.append(urljoin(page_url, text_value))
    out.images = extract_images(soup, page_url, ld_images, meta, max_images, min_image_px)
    if len(out.images) < 3 and out.embedded.images:  # shells whose pictures only exist in embedded data
        for url in out.embedded.images:
            absolute = urljoin(page_url, url)
            if absolute not in out.images and _image_ok(absolute) and not BAD_IMAGE_HINT.search(absolute):
                out.images.append(absolute)
            if len(out.images) >= max_images:
                break

    out.logo, out.logo_source, out.favicon = _logo_and_favicon(soup, page_url, meta, _ld_text(biz.get("logo")))

    links, whatsapp, emails, social, link_phones = extract_links(soup, page_url, home_url)
    out.links = links
    if not links and out.embedded.links:
        for raw in out.embedded.links:
            absolute = normalize_link(raw, page_url)
            if absolute and is_same_site(absolute, home_url) and absolute.rstrip("/") != home_url.rstrip("/"):
                out.links.append(LinkInfo(absolute, "", "nav"))
    out.whatsapp, out.emails, out.social = whatsapp, emails, social
    for key in ("sameAs",):
        same_as = biz.get(key)
        for item in same_as if isinstance(same_as, list) else [same_as]:
            if isinstance(item, str) and item.startswith("http") and item not in out.social and len(out.social) < 8:
                out.social.append(item)
    email = _ld_text(biz.get("email"))
    if email and email not in out.emails:
        out.emails.append(email.replace("mailto:", ""))

    phone_groups: list[list[Phone]] = [link_phones]
    ld_phone = _ld_text(biz.get("telephone"))
    if ld_phone:
        phone_groups.append(find_phones_in_text(ld_phone, "json_ld") or [])
    for zone_tag, source in (("header", "header"), ("footer", "footer")):
        zone_el = soup.find(zone_tag)
        if zone_el is not None:
            phone_groups.append(find_phones_in_text(zone_el.get_text(" ", strip=True), source))  # type: ignore[arg-type]
    if not any(phone_groups) or phone_source:
        body_source = phone_source or "body"
        body_text = text[:60_000]
        phone_groups.append(find_phones_in_text(body_text, body_source)[:4])  # type: ignore[arg-type]
    out.phones = merge_phones(phone_groups)

    out.address = extract_address(soup, _ld_address(biz.get("address")))
    out.category = _category_from_types(nodes)
    out.services = extract_services(soup, _ld_services(biz))
    out.offer = extract_offer(soup)
    out.cta = extract_cta(soup)
    out.brand_colors = extract_brand_colors(soup, meta)
    out.text_excerpt = build_text_excerpt(soup, excerpt_chars)
    if not out.text_excerpt and out.embedded.texts:
        out.text_excerpt = clean(" ".join(out.embedded.texts), excerpt_chars)
    return out
