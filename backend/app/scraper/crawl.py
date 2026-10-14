"""robots.txt, sitemap.xml and the choice of which 5-10 inner pages to read in phase 2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .extract import LinkInfo, is_same_site, normalize_link
from .fetch import Deadline, Fetcher

SITEMAP_BYTES = 2 * 1024 * 1024
ROBOTS_BYTES = 512 * 1024
MAX_SITEMAP_URLS = 400

# (kind, regex on url path + link label). First match decides the page kind; order = priority.
PRIORITY_KINDS: list[tuple[str, re.Pattern]] = [
    ("about", re.compile(r"\babout(?:[-_ ]?us)?\b|\bour[-_ ]?story\b|\bwho[-_ ]?we[-_ ]?are\b|\bcompany\b", re.I)),
    ("services", re.compile(r"\bservices?\b|\bwhat[-_ ]?we[-_ ]?(?:do|offer)\b|\boffering", re.I)),
    ("products", re.compile(r"\bproducts?\b|\bmenu\b|\bcatalog(?:ue)?\b|\bcollections?\b|\brooms?\b|\bpackages?\b|\bcourses?\b", re.I)),
    ("pricing", re.compile(r"\bpric(?:e|es|ing)\b|\bplans?\b|\brates?\b|\btariff", re.I)),
    ("contact", re.compile(r"\bcontact(?:[-_ ]?us)?\b|\breach[-_ ]?us\b|\bget[-_ ]?in[-_ ]?touch\b|\blocations?\b|\bfind[-_ ]?us\b|\bvisit[-_ ]?us\b", re.I)),
    ("team", re.compile(r"\bteam\b|\bour[-_ ]?people\b|\bleadership\b|\bdoctors?\b|\bstaff\b", re.I)),
    ("solutions", re.compile(r"\bsolutions?\b|\bindustries\b|\buse[-_ ]?cases?\b", re.I)),
    ("offers", re.compile(r"\boffers?\b|\bdeals?\b|\bpromotions?\b|\bdiscounts?\b", re.I)),
]
KIND_WEIGHT = {"about": 100, "services": 95, "products": 92, "contact": 90, "pricing": 85, "solutions": 80, "team": 75, "offers": 70}
SKIP_RE = re.compile(
    r"privacy|terms|conditions|\blogin\b|log-in|signin|sign-in|signup|sign-up|register|\bcart\b|checkout|\baccount\b|my-account|"
    r"wp-admin|wp-login|wp-json|/feed|/tag/|/category/|/author/|/search|cookie|refund|disclaimer|returns?-policy|"
    r"sitemap|/cdn-cgi/|\?replytocom|/wishlist|/compare|/blog/20\d\d|/20\d\d/\d\d/|/news/20\d\d|\.xml$|/amp/?$|/page/\d+",
    re.I,
)
BLOG_RE = re.compile(r"/(blog|news|articles?|posts?|press|stories)/[^/]+", re.I)
SOURCE_WEIGHT = {"sitemap": 30, "nav": 20, "footer": 10}


@dataclass
class Candidate:
    """An inner page that might be worth reading."""

    url: str
    kind: str
    score: float
    source: str
    label: str = ""


def classify(url: str, label: str = "") -> str:
    """Return the page kind (about, services, ...) or '' when it is not a priority page."""
    haystack = f"{urlparse(url).path.replace('/', ' ')} {label}"
    for kind, pattern in PRIORITY_KINDS:
        if pattern.search(haystack):
            return kind
    return ""


def should_skip(url: str) -> bool:
    """True for legal, account, cart, feed and dated-blog pages that tell us nothing about the business."""
    parsed = urlparse(url)
    target = parsed.path + ("?" + parsed.query if parsed.query else "")
    if SKIP_RE.search(target):
        return True
    return bool(BLOG_RE.search(parsed.path))


def select_pages(
    home_url: str,
    links: Iterable[LinkInfo],
    sitemap_urls: Iterable[str],
    limit: int,
    exclude: Iterable[str] = (),
) -> list[Candidate]:
    """Pick up to `limit` same-site pages. Priority kinds first; ties broken sitemap > nav > footer."""
    excluded = {u.rstrip("/") for u in exclude} | {home_url.rstrip("/")}
    candidates: dict[str, Candidate] = {}

    def consider(url: str, source: str, label: str = "") -> None:
        """Score one URL and keep the best entry per URL."""
        key = url.rstrip("/")
        if key in excluded or not is_same_site(url, home_url) or should_skip(url):
            return
        kind = classify(url, label)
        depth = max(0, len([p for p in urlparse(url).path.split("/") if p]) - 1)
        score = KIND_WEIGHT.get(kind, 0) + SOURCE_WEIGHT[source] - depth * 4
        if not kind:
            score -= 25  # non-priority pages only fill leftover slots
        current = candidates.get(key)
        if current is None or current.score < score:
            candidates[key] = Candidate(url, kind, score, source, label)

    for url in sitemap_urls:
        consider(url, "sitemap")
    for link in links:
        if link.zone in SOURCE_WEIGHT:
            consider(link.url, link.zone, link.label)
    ranked = sorted(candidates.values(), key=lambda c: -c.score)
    chosen: list[Candidate] = []
    seen_kinds: dict[str, int] = {}
    for cand in ranked:  # at most 2 pages of one kind so the crawl covers about/services/contact/...
        if cand.kind and seen_kinds.get(cand.kind, 0) >= 2:
            continue
        seen_kinds[cand.kind] = seen_kinds.get(cand.kind, 0) + 1
        chosen.append(cand)
        if len(chosen) >= limit:
            break
    return chosen


# --------------------------------------------------------------------------- sitemap


def parse_sitemap(text: str) -> tuple[list[str], list[str]]:
    """Return (page urls, child sitemap urls) from sitemap XML. Regex based on purpose: no XML entity expansion."""
    locs = [re.sub(r"^<!\[CDATA\[|\]\]>$", "", m.strip()) for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", text[:SITEMAP_BYTES], re.S | re.I)]
    locs = [loc.replace("&amp;", "&") for loc in locs if loc]
    children = [loc for loc in locs if loc.lower().endswith((".xml", ".xml.gz")) or "sitemap" in urlparse(loc).path.lower()]
    pages = [loc for loc in locs if loc not in children]
    return pages[:MAX_SITEMAP_URLS], children[:3]


async def fetch_sitemap_urls(fetcher: Fetcher, home_url: str, hints: Iterable[str], deadline: Deadline) -> list[str]:
    """Read /sitemap.xml (and sitemaps named in robots.txt), following at most two child sitemaps."""
    root = urlparse(home_url)
    base = f"{root.scheme}://{root.netloc}"
    queue = list(dict.fromkeys([*hints, base + "/sitemap.xml"]))[:3]
    pages: list[str] = []
    visited = 0
    while queue and visited < 4 and len(pages) < MAX_SITEMAP_URLS and not deadline.expired:
        url = queue.pop(0)
        visited += 1
        result = await fetcher.get(url, deadline.child(5), as_text=True, max_bytes=SITEMAP_BYTES)
        if not result.ok:
            continue
        found, children = parse_sitemap(result.html)
        for child in children:
            if child not in queue and len(queue) < 3:
                queue.append(child)
        for page in found:
            normalized = normalize_link(page, base)
            if normalized and is_same_site(normalized, home_url):
                pages.append(normalized)
    return list(dict.fromkeys(pages))


# --------------------------------------------------------------------------- robots.txt


class RobotsPolicy:
    """robots.txt for one site, fetched once per scrape. Missing or unreadable robots.txt means 'allowed'."""

    def __init__(self, bot_name: str, enabled: bool = True):
        """Create an empty (allow-all) policy."""
        self.bot_name = bot_name
        self.enabled = enabled
        self.sitemaps: list[str] = []
        self._parser: Optional[RobotFileParser] = None
        self.loaded = False

    async def load(self, fetcher: Fetcher, home_url: str, deadline: Deadline) -> None:
        """Fetch and parse robots.txt (best effort, short timeout)."""
        self.loaded = True
        if not self.enabled:
            return
        root = urlparse(home_url)
        result, _ = await fetcher.get_with_fallback(
            f"{root.scheme}://{root.netloc}/robots.txt", deadline.child(4), as_text=True, max_bytes=ROBOTS_BYTES
        )
        if not result.ok:
            return
        text = result.html
        self.sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)[:3]
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        self._parser = parser

    def allowed(self, url: str) -> bool:
        """True when this bot may fetch the URL."""
        if not self.enabled or self._parser is None:
            return True
        try:
            return self._parser.can_fetch(self.bot_name, url)
        except Exception:
            return True
