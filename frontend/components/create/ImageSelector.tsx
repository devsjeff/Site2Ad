"use client";

import React, { useState } from "react";

interface ImageSelectorProps {
  images: string[]; // image addresses found by the website scan
  selected: string[];
  max: number;
  onChange: (selected: string[]) => void;
  title: string;
  hint: string;
}

// Grid of website images; the user picks which ones (and in which order) go into the ad. Numbers show the order.
export function ImageSelector({ images, selected, max, onChange, title, hint }: ImageSelectorProps) {
  const [broken, setBroken] = useState<ReadonlySet<string>>(new Set());
  const visible = images.filter((url) => !broken.has(url) && !/\.(svg|gif)(\?|$)/i.test(url));
  if (visible.length === 0) {
    return <p className="rounded-xl border border-line bg-surface p-4 text-sm text-muted">The website scan found no usable images.</p>;
  }

  // Add or remove one image (the order of clicks is the play order).
  function toggle(url: string) {
    if (selected.includes(url)) onChange(selected.filter((item) => item !== url));
    else if (selected.length < max) onChange([...selected, url]);
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-sm font-medium text-ink">{title}</p>
        {selected.length > 0 && <button type="button" onClick={() => onChange([])} className="text-xs font-medium text-accent hover:underline">Clear</button>}
      </div>
      <p className="mb-3 text-xs text-muted">{hint} {selected.length === 0 ? "None picked: the best images are used automatically." : `${selected.length} of up to ${max} picked.`}</p>
      <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
        {visible.slice(0, 12).map((url) => {
          const position = selected.indexOf(url);
          const active = position >= 0;
          return (
            <li key={url}>
              <button
                type="button"
                onClick={() => toggle(url)}
                aria-pressed={active}
                aria-label={active ? `Website image, number ${position + 1} (selected)` : "Website image (not selected)"}
                className={`relative block aspect-square w-full overflow-hidden rounded-lg border-2 transition-all ${active ? "border-accent ring-2 ring-accent/30" : "border-line opacity-80 hover:border-accent/60 hover:opacity-100"}`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-full w-full object-cover" onError={() => setBroken((prev) => new Set(prev).add(url))} />
                {active && <span className="absolute left-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-[11px] font-semibold text-white">{position + 1}</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
