"use client";

import React, { useState } from "react";
import type { ConfigOption } from "@/lib/types";
import { OptionCard } from "../ui/OptionCard";

const ICONS: Record<string, string> = {
  auto: "✨", ugc: "🤳", product: "📦", brand_awareness: "💡", offer: "🏷️", animation_3d: "🧊", explainer: "🧭", problem_solution: "🛠️",
  testimonial: "💬", app_website: "📱", event: "🎪", local: "📍", seasonal: "🪔", lead_generation: "📞", recruitment: "🤝",
  public_awareness: "📣", retargeting: "🔁", qr_code: "🔳",
};

const FIRST_ROWS = 8; // the rest open with "Show all", so the screen stays short

interface AdTypePickerProps {
  types: ConfigOption[];
  value: string;
  onChange: (id: string) => void;
}

// What kind of ad to make. It steers the AI prompt, the on-screen text and the call to action.
export function AdTypePicker({ types, value, onChange }: AdTypePickerProps) {
  const [open, setOpen] = useState(false);
  if (types.length === 0) return null;
  const hiddenPick = types.findIndex((type) => type.id === value) >= FIRST_ROWS;
  const shown = open || hiddenPick ? types : types.slice(0, FIRST_ROWS);
  const note = types.find((type) => type.id === value)?.note;
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-bold text-ink">What kind of ad?</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {shown.map((type) => (
          <OptionCard key={type.id} compact icon={ICONS[type.id]} title={type.label} description={type.hint} selected={value === type.id} onClick={() => onChange(type.id)} />
        ))}
      </div>
      {note && <p className="animate-expand rounded-2xl border border-accent/25 bg-accent-soft/50 px-4 py-2.5 text-xs text-ink">{note}</p>}
      {types.length > FIRST_ROWS && !hiddenPick && (
        <button type="button" onClick={() => setOpen(!open)} className="text-xs font-bold text-accent hover:underline" aria-expanded={open}>
          {open ? "Show fewer" : `Show all ${types.length} types`}
        </button>
      )}
    </div>
  );
}
