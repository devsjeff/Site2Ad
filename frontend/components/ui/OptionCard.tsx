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
  compact?: boolean; // small pill-like card (platforms, goals)
}

// A selectable card used for goals, platforms, styles, tones and creation modes.
export function OptionCard({ icon, title, description, selected, onClick, disabled = false, badge, note, compact = false }: OptionCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      disabled={disabled}
      className={`group relative flex w-full flex-col items-start rounded-2xl border-2 text-left transition-all duration-200 ${compact ? "p-3" : "p-4"} ${
        disabled
          ? "cursor-not-allowed border-line bg-surface/60 opacity-55"
          : `hover:-translate-y-1 hover:shadow-glow ${selected ? "ring-brand shadow-glow" : "border-line bg-surface/85 hover:border-accent/50"}`
      }`}
    >
      {selected && !disabled && (
        <span className="bg-brand animate-popIn absolute right-2.5 top-2.5 flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold text-white" aria-hidden="true">✓</span>
      )}
      {icon && (
        <span className={`flex items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6 ${compact ? "mb-1.5 h-8 w-8 text-lg" : "mb-3 h-11 w-11 text-2xl"} ${selected ? "bg-accent-soft" : "bg-background"}`} aria-hidden="true">
          {icon}
        </span>
      )}
      <span className="pr-6 text-sm font-bold text-ink">{title}</span>
      {description && <span className="mt-1 text-xs leading-relaxed text-muted">{description}</span>}
      {badge && <span className={`mt-2 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${selected ? "bg-accent text-white" : "bg-accent-soft text-accent"}`}>{badge}</span>}
      {note && <span className="mt-2 text-xs font-medium text-danger">{note}</span>}
    </button>
  );
}
