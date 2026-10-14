"use client";

import React from "react";

interface OptionCardProps {
  icon?: string;
  title: string;
  description?: string;
  selected: boolean;
  onClick: () => void;
  disabled?: boolean;
  badge?: string; // short note under the description, e.g. "No AI video"
  note?: string; // why the card is disabled
}

// A selectable card used for goals, platforms, styles, tones and creation modes.
export function OptionCard({ icon, title, description, selected, onClick, disabled = false, badge, note }: OptionCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      disabled={disabled}
      className={`flex w-full flex-col items-start rounded-xl border-2 p-4 text-left transition-all ${
        disabled
          ? "cursor-not-allowed border-line bg-surface opacity-60"
          : `hover:-translate-y-0.5 hover:shadow-md ${selected ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-accent/60"}`
      }`}
    >
      {icon && <span className="mb-2 text-2xl" aria-hidden="true">{icon}</span>}
      <span className="text-sm font-semibold text-ink">{title}</span>
      {description && <span className="mt-1 text-xs leading-relaxed text-muted">{description}</span>}
      {badge && <span className="mt-2 rounded-md border border-line bg-background px-2 py-0.5 text-[11px] font-medium text-muted">{badge}</span>}
      {note && <span className="mt-2 text-xs font-medium text-danger">{note}</span>}
    </button>
  );
}
