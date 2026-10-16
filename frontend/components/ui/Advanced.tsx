import React from "react";

// A collapsible section for optional settings ("Advanced options"). Closed by default.
export function Advanced({ title = "Advanced options", hint, children, defaultOpen = false }: {
  title?: string; hint?: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  return (
    <details className="group rounded-2xl border border-line bg-surface/70 transition-colors open:bg-surface/90" open={defaultOpen}>
      <summary className="flex items-center justify-between gap-3 px-5 py-4">
        <span className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent-soft text-sm transition-transform group-open:rotate-90" aria-hidden="true">⚙️</span>
          <span>
            <span className="block text-sm font-bold text-ink">{title}</span>
            {hint && <span className="block text-xs text-muted">{hint}</span>}
          </span>
        </span>
        <svg className="chevron h-4 w-4 text-muted transition-transform duration-300" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M4 6l4 4 4-4" />
        </svg>
      </summary>
      <div className="details-body space-y-6 border-t border-line px-5 pb-5 pt-5">{children}</div>
    </details>
  );
}
