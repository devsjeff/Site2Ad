import React from "react";

type Tone = "info" | "warn" | "error" | "success";

const TONES: Record<Tone, string> = {
  info: "border-accent/25 bg-accent-soft/50 text-ink",
  warn: "border-warn/40 bg-warn/10 text-ink",
  error: "border-danger/40 bg-danger/10 text-ink",
  success: "border-ok/40 bg-ok/10 text-ink",
};

// Coloured message box (info, success, warning, error).
export function Alert({ tone = "info", title, children }: { tone?: Tone; title?: string; children?: React.ReactNode }) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`animate-fadeUp rounded-2xl border px-4 py-3 text-sm ${TONES[tone]}`}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? "mt-1 text-muted" : ""}>{children}</div>}
    </div>
  );
}
