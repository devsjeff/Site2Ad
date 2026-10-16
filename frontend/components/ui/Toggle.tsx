import React from "react";

// An on/off switch with a title and an explanation.
export function Toggle({ checked, onChange, title, help }: { checked: boolean; onChange: (value: boolean) => void; title: string; help?: string }) {
  return (
    <label className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 text-sm transition-all hover:border-accent/50 ${checked ? "border-accent/40 bg-accent-soft/40" : "border-line bg-surface/80"}`}>
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors duration-300 peer-focus-visible:ring-4 peer-focus-visible:ring-accent/25 ${checked ? "bg-brand" : "bg-line"}`} aria-hidden="true">
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all duration-300 ${checked ? "left-[22px]" : "left-0.5"}`} />
      </span>
      <span>
        <span className="font-semibold text-ink">{title}</span>
        {help && <span className="mt-0.5 block text-xs text-muted">{help}</span>}
      </span>
    </label>
  );
}
