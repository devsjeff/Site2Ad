"use client";

import React, { useState } from "react";
import { assetUrl } from "@/lib/api";
import type { AssetInfo, HeroRef } from "@/lib/types";

interface Candidate {
  key: string;
  src: string;
  hero: HeroRef;
  label: string;
}

interface ImagePickerProps {
  scraped: string[];
  photos: AssetInfo[];
  selected: HeroRef | null;
  onSelect: (hero: HeroRef) => void;
}

/** Candidate images for the ONE hero (first frame of the video). */
export function candidatesFor(scraped: string[], photos: AssetInfo[]): Candidate[] {
  return [
    ...photos.map((p): Candidate => ({ key: `asset:${p.asset_id}`, src: assetUrl(p.asset_id), hero: { source: "asset", asset_id: p.asset_id }, label: "Your photo" })),
    ...scraped.map((url): Candidate => ({ key: `url:${url}`, src: url, hero: { source: "scraped", url }, label: "From your website" })),
  ];
}

// Stable key that identifies a hero choice (used to highlight the selection).
export function heroKey(hero: HeroRef | null): string {
  if (!hero) return "";
  return hero.source === "asset" ? `asset:${hero.asset_id}` : `url:${hero.url}`;
}

// Grid of candidate hero images; the user picks one.
export function ImagePicker({ scraped, photos, selected, onSelect }: ImagePickerProps) {
  const [broken, setBroken] = useState<ReadonlySet<string>>(new Set());
  const candidates = candidatesFor(scraped, photos).filter((c) => !broken.has(c.key));
  if (candidates.length === 0) return null;
  const current = heroKey(selected) || candidates[0].key;
  return (
    <div>
      <p className="mb-1 text-sm font-medium text-ink">Pick the image your video starts from</p>
      <p className="mb-3 text-xs text-muted">The video begins with this one photo, so choose a clear picture of your product, shop or logo. Your own photos are listed first.</p>
      <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
        {candidates.slice(0, 12).map((candidate) => {
          const active = candidate.key === current;
          return (
            <li key={candidate.key}>
              <button
                type="button"
                onClick={() => onSelect(candidate.hero)}
                aria-pressed={active}
                aria-label={`${candidate.label}${active ? " (selected)" : ""}`}
                className={`relative block aspect-square w-full overflow-hidden rounded-lg border-2 transition-all ${active ? "border-accent ring-2 ring-accent/30" : "border-line hover:border-accent/60"}`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={candidate.src} alt={candidate.label} loading="lazy" referrerPolicy="no-referrer" className="h-full w-full object-cover" onError={() => setBroken((prev) => new Set(prev).add(candidate.key))} />
                {active && <span className="absolute left-1 top-1 rounded bg-accent px-1.5 py-0.5 text-[10px] font-semibold text-white">First frame</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
