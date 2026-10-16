import React from "react";

// Horizontal progress bar with an optional label.
export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const percent = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={label ?? "Progress"} className="h-2.5 w-full overflow-hidden rounded-full bg-accent-soft">
      <div className="bg-brand animate-gradient shine shine-loop h-full rounded-full transition-all duration-700" style={{ width: `${percent}%` }} />
    </div>
  );
}
