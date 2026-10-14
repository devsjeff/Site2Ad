// The editable business details shown in step 1, and how they are merged with what the scan finds.

import type { BusinessOverrides, SiteInfo } from "./types";

export interface BusinessDraft {
  name: string;
  category: string; // a catalog id such as "food_dining"; empty means "use what the website says"
  description: string;
  phone: string;
  address: string;
  offer: string;
  cta: string;
}

export type DraftField = keyof BusinessDraft;

export const EMPTY_DRAFT: BusinessDraft = { name: "", category: "", description: "", phone: "", address: "", offer: "", cta: "" };

/** Fields that can come from a website scan (category is chosen by the user, the scan only suggests one). */
const SCRAPED_FIELDS: DraftField[] = ["name", "description", "phone", "address", "offer", "cta"];

/** Draft values found by the scan. */
export function draftFromSite(site: SiteInfo | null | undefined): BusinessDraft {
  if (!site) return { ...EMPTY_DRAFT };
  return {
    ...EMPTY_DRAFT,
    name: site.name || "",
    description: site.description || "",
    phone: site.phone || "",
    address: site.address || "",
    offer: site.offer || "",
    cta: site.cta || "",
  };
}

/** Update only the fields the user has not touched, so a later (better) scan result never overwrites typing. */
export function mergeScan(current: BusinessDraft, touched: ReadonlySet<DraftField>, site: SiteInfo | null | undefined): BusinessDraft {
  const found = draftFromSite(site);
  const next = { ...current };
  for (const field of SCRAPED_FIELDS) {
    if (!touched.has(field)) next[field] = found[field];
  }
  return next;
}

/** Turn the draft into what the backend expects. A scraped fact the user emptied is sent in `omit`, so it is not used. */
export function toOverrides(draft: BusinessDraft, touched: ReadonlySet<DraftField>, websiteUrl: string): BusinessOverrides {
  const omit: string[] = [];
  for (const field of ["description", "phone", "address", "offer", "cta"] as const) {
    if (touched.has(field) && !draft[field].trim()) omit.push(field);
  }
  return {
    name: draft.name.trim(),
    website_url: websiteUrl,
    category: draft.category,
    description: draft.description.trim(),
    phone: draft.phone.trim(),
    address: draft.address.trim(),
    offer: draft.offer.trim(),
    cta: draft.cta.trim(),
    services: [],
    omit,
  };
}
