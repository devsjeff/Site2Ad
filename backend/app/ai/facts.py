"""FactSheet: the only business facts the prompt builder (and the final overlay) may use.

Facts come from the scrape result and from what the user typed. Anything the user typed wins and counts as verified.
Missing facts stay empty: nothing is ever invented to fill a gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .. import catalog
from ..schemas import AdOptions, BusinessOverrides, ScrapeResult
from .relevance import Relevance, check_relevance, identity_text


class MissingBusinessName(ValueError):
    """Raised when no business name could be determined from the scrape or the user."""


# Inner pages whose text is most likely to describe what the advertiser sells (read first).
PAGE_PRIORITY = ("offer", "offers", "pricing", "price", "product", "products", "services", "service", "menu", "shop", "about", "home")


@dataclass
class FactSource:
    """Where one fact came from: typed by the user, or found on the website (which page)."""

    field: str
    origin: str  # "user" | "website"
    url: str = ""
    page: str = ""


@dataclass
class FactSheet:
    """Verified facts about one business."""

    name: str
    category: str = ""
    description: str = ""
    services: list[str] = field(default_factory=list)
    offer: str = ""
    cta: str = ""
    phone: str = ""
    address: str = ""
    website: str = ""
    language: str = ""
    brand_colors: list[str] = field(default_factory=list)
    excerpts: list[tuple[str, str]] = field(default_factory=list)  # (label, text): untrusted website text
    user_notes: str = ""
    user_fields: set[str] = field(default_factory=set)
    sources: dict[str, FactSource] = field(default_factory=dict)  # field name -> provenance of the value in use
    rejected: list[str] = field(default_factory=list)  # scraped claims left out because they are about something else
    conflicts: list[str] = field(default_factory=list)  # e.g. several different phone numbers on the website

    def allowed_text(self) -> str:
        """Lower-case text of everything the prompt is allowed to mention (used by the fact guard).

        Only the structured, checked facts count: a number or claim that appears somewhere in raw website text (which can
        carry ads for other companies) is NOT automatically allowed in an ad.
        """
        parts = [
            self.name, self.category, self.description, " ".join(self.services), self.offer, self.cta, self.phone,
            self.address, self.website, self.user_notes,
        ]
        return " \n".join(p for p in parts if p).lower()

    def identity(self) -> str:
        """What the business is (name, category, services, domain, description): the yardstick for relevance checks."""
        return identity_text(self.name, self.category, self.services, self.website, self.description)

    def relevance(self, claim: str) -> Relevance:
        """Is this claim about this business? (core identity = name, category, domain, page title; see relevance.py)"""
        source = self.sources.get("name")
        core = identity_text(self.name, self.category, [], self.website) + " " + (source.page if source else "")
        context = list(self.services) + re.split(r"(?<=[.!?])\s+", self.description)
        return check_relevance(claim, core, context, [text for _, text in self.excerpts])

    def public_summary(self) -> dict:
        """Facts as a plain dict (for logs and API debugging); excludes long website text."""
        return {
            "name": self.name, "category": self.category, "description": self.description, "services": self.services,
            "offer": self.offer, "cta": self.cta, "phone": self.phone, "address": self.address, "website": self.website,
        }


def _clip(text: str, limit: int) -> str:
    """Collapse whitespace and cut to limit characters."""
    return " ".join((text or "").split())[:limit].strip()


def build_fact_sheet(scrape: Optional[ScrapeResult], business: BusinessOverrides, options: AdOptions) -> FactSheet:
    """Merge scraped facts with user-typed facts (user wins). Raises MissingBusinessName if there is no name."""
    site = scrape.site if scrape else None
    user_fields: set[str] = set()

    omit = set(business.omit)

    page_url = (scrape.final_url or scrape.home_url) if scrape else ""
    page_title = site.title if site else ""
    sources: dict[str, FactSource] = {}

    def pick(field_name: str, user_value: str, scraped_value: str, limit: int) -> str:
        """User value first, then scraped value (unless the user deleted it); remember who supplied it and from where."""
        if user_value and user_value.strip():
            user_fields.add(field_name)
            sources[field_name] = FactSource(field_name, "user")
            return _clip(user_value, limit)
        value = "" if field_name in omit else _clip(scraped_value, limit)
        if value:
            sources[field_name] = FactSource(field_name, "website", page_url, page_title)
        return value

    name = pick("name", business.name, (site.name or "") if site else "", 120)
    if not name and site and site.title:
        name = _clip(re.split(r"\s+[|\-–—:]\s+", site.title)[0], 120)
    if not name:
        raise MissingBusinessName("A business name is required. Enter it, or scan a website that has one.")

    scraped_services = [] if "services" in omit or not site else site.services
    services = [_clip(s, 60) for s in business.services if s.strip()] or [_clip(s, 60) for s in scraped_services]
    if business.services:
        user_fields.add("services")
    if business.category:
        category = catalog.CATEGORIES.get(business.category, _clip(business.category, 60))
        user_fields.add("category")
    else:
        category = "" if "category" in omit or not site else _clip(site.category, 60)

    excerpts: list[tuple[str, str]] = []
    if scrape:
        if site and site.text_excerpt:
            excerpts.append(("home", _clip(site.text_excerpt, 1200)))
        rank = {kind: index for index, kind in enumerate(PAGE_PRIORITY)}
        pages = sorted(scrape.pages, key=lambda page: rank.get((page.kind or "").lower(), len(rank)))  # most relevant pages first
        for page in pages[:6]:
            if page.text_excerpt:
                excerpts.append((page.kind or "page", _clip(page.text_excerpt, 500)))

    website = business.website_url.strip() if business.website_url.strip() else ""
    if website:
        user_fields.add("website")
    elif scrape:
        website = scrape.home_url or scrape.final_url

    if "name" not in sources:
        sources["name"] = FactSource("name", "user" if "name" in user_fields else "website", page_url, page_title)
    if services:
        sources["services"] = FactSource("services", "user" if business.services else "website", "" if business.services else page_url, "" if business.services else page_title)
    if category:
        sources["category"] = FactSource("category", "user" if "category" in user_fields else "website", "" if "category" in user_fields else page_url)

    sheet = FactSheet(
        name=name,
        category=category,
        description=pick("description", business.description, site.description if site else "", 400),
        services=services[:8],
        offer=pick("offer", business.offer, site.offer if site else "", 140),
        cta=pick("cta", business.cta, site.cta if site else "", 60),
        phone=pick("phone", business.phone, site.phone if site else "", 40),
        address=pick("address", business.address, site.address if site else "", 200),
        website=website,
        language=(site.language if site else "") or "",
        brand_colors=list(site.brand_colors) if site else [],
        excerpts=excerpts,
        user_notes=_clip(options.special_instructions, 600),
        user_fields=user_fields,
        sources=sources,
    )
    _drop_unrelated_claims(sheet)
    if site and "phone" not in user_fields:
        numbers = list(dict.fromkeys(p.number for p in site.phones if p.number))
        if len(numbers) > 1:
            sheet.conflicts.append(f"The website shows {len(numbers)} different phone numbers; the first one ({numbers[0]}) is used. Enter the right one if needed.")
    return sheet


PRICE_RE = re.compile(r"\d|\$|₹|€|£")


def _drop_unrelated_claims(sheet: FactSheet) -> None:
    """Remove scraped claims about another business, and website text carrying the same brands (user values are kept)."""
    banned: set[str] = set()
    for field_name in ("offer", "cta"):
        value = getattr(sheet, field_name)
        if not value or field_name in sheet.user_fields:
            continue
        verdict = sheet.relevance(value)
        if not verdict.relevant:
            setattr(sheet, field_name, "")
            sheet.sources.pop(field_name, None)
            banned.update(verdict.foreign)
            sheet.rejected.append(f"Left out the website {field_name} \"{value}\": {verdict.reason}.")

    def carries_banned(text: str) -> bool:
        """True when the text names a brand from a rejected claim."""
        return any(re.search(rf"(?<![A-Za-z]){re.escape(brand)}(?![A-Za-z])", text, re.I) for brand in banned)

    if sheet.description and "description" not in sheet.user_fields:
        kept = []
        for sentence in re.split(r"(?<=[.!?])\s+", sheet.description):
            verdict = sheet.relevance(sentence)
            if carries_banned(sentence) or (not verdict.relevant and PRICE_RE.search(sentence)):
                sheet.rejected.append(f"Left out part of the website description (\"{_clip(sentence, 80)}\"): it is about another business.")
                banned.update(verdict.foreign)
            else:
                kept.append(sentence)
        sheet.description = " ".join(kept)
    if "services" not in sheet.user_fields:
        services = []
        for service in sheet.services:
            if carries_banned(service):
                sheet.rejected.append(f"Left out the website item \"{service}\": it belongs to another business.")
            else:
                services.append(service)
        sheet.services = services
