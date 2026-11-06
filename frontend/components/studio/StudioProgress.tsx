"use client";

import React from "react";
import { seconds, STAGE_ICONS } from "@/lib/studio";
import type { StudioResponse } from "@/lib/types";
import { Button } from "../ui/Button";
import { ProgressBar } from "../ui/ProgressBar";
import { Spinner } from "../ui/Spinner";

interface StudioProgressProps {
  job: StudioResponse;
  cancelling: boolean;
  onCancel: () => void;
}

// The seven stages with what each one found, while the job works.
export function StudioProgress({ job, cancelling, onCancel }: StudioProgressProps) {
  return (
    <section className="space-y-6 animate-fadeUp" aria-live="polite">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-ink">Making your <span className="text-brand">video</span></h1>
        <p className="mt-1.5 truncate text-sm text-muted">{job.url}</p>
      </div>

      <div className="space-y-4 rounded-3xl border border-line bg-surface/85 p-5 shadow-glow">
        <div className="flex items-center gap-3 text-sm font-semibold text-ink">
          <Spinner />
          <span>{job.status === "queued" ? "Waiting for its turn…" : job.message || "Working…"}</span>
        </div>
        <ProgressBar value={job.progress} label="Studio progress" />
        <ol className="space-y-2">
          {job.stages.map((stage, index) => (
            <li key={stage.name} className={`flex items-start gap-3 rounded-2xl px-3 py-2.5 text-sm transition-colors ${stage.status === "running" ? "bg-accent-soft/60" : ""}`}>
              <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                stage.status === "done" ? "bg-ok text-white" : stage.status === "running" ? "bg-brand animate-pulse text-white" : stage.status === "failed" ? "bg-danger text-white" : "bg-line text-muted"}`} aria-hidden="true">
                {stage.status === "done" ? "✓" : stage.status === "failed" ? "×" : index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className={`block font-semibold ${stage.status === "pending" ? "text-muted" : "text-ink"}`}>
                  <span aria-hidden="true">{STAGE_ICONS[stage.name] ?? "•"} </span>{stage.label}
                </span>
                {stage.summary && <span className="block text-xs text-muted">{stage.summary}</span>}
              </span>
              {stage.status === "done" && <span className="text-xs tabular-nums text-muted">{seconds(stage.seconds)}</span>}
            </li>
          ))}
        </ol>
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted">You can leave this page and come back with the same link.</p>
          <Button variant="secondary" onClick={onCancel} loading={cancelling} className="px-4 py-2 text-xs">Cancel</Button>
        </div>
      </div>
    </section>
  );
}
