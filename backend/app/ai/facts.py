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


class MissingBusinessName(ValueError):
    """Raised when no business name could be determined from the scrape or the user."""


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

    def allowed_text(self) -> str:
        """Lower-case text of everything the prompt is allowed to mention (used by the fact guard)."""
        parts = [
            self.name, self.category, self.description, " ".join(self.services), self.offer, self.cta, self.phone,
            self.address, self.website, self.user_notes, " ".join(text for _, text in self.excerpts),
        ]
        return " \n".join(p for p in parts if p).lower()

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

    def pick(field_name: str, user_value: str, scraped_value: str, limit: int) -> str:
        """User value first, then scraped value (unless the user deleted it); remember when the user supplied it."""
        if user_value and user_value.strip():
            user_fields.add(field_name)
            return _clip(user_value, limit)
        return "" if field_name in omit else _clip(scraped_value, limit)

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
        for page in scrape.pages[:6]:
            if page.text_excerpt:
                excerpts.append((page.kind or "page", _clip(page.text_excerpt, 500)))

    website = business.website_url.strip() if business.website_url.strip() else ""
    if website:
        user_fields.add("website")
    elif scrape:
        website = scrape.home_url or scrape.final_url

    return FactSheet(
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
    )
