import React from "react";
import type { JobResponse, ScrapeStage } from "@/lib/types";
import { ProgressBar } from "../ui/ProgressBar";
import { Spinner } from "../ui/Spinner";

const STEPS: { stage: ScrapeStage; label: string }[] = [
  { stage: "fetching", label: "Opening your website" },
  { stage: "rendering", label: "Reading the page" },
  { stage: "extracting", label: "Finding your business details" },
  { stage: "ad_ready", label: "Ready to draft your ad" },
];

const ORDER: ScrapeStage[] = ["queued", "fetching", "rendering", "extracting", "ad_ready"];

// Progress display while the website is being scanned.
export function ScanProgress({ job }: { job: JobResponse | null }) {
  const stage: ScrapeStage = job?.stage ?? "queued";
  const position = ORDER.indexOf(stage);
  const morePages = job?.phase2.state === "running" && job.phase2.pages_total > 0;
  return (
    <div className="space-y-4 rounded-2xl border border-line bg-surface/85 p-5 animate-fadeUp" aria-live="polite">
      <div className="flex items-center gap-3 text-sm font-medium text-ink">
        {!job?.is_final && <Spinner />}
        <span>{job?.message || "Starting the scan…"}</span>
      </div>
      <ProgressBar value={job?.progress ?? 3} label="Website scan progress" />
      <ul className="space-y-1.5 text-sm">
        {STEPS.map((step) => {
          const done = ORDER.indexOf(step.stage) < position || (step.stage === "ad_ready" && position >= ORDER.indexOf("ad_ready"));
          return (
            <li key={step.stage} className={done ? "text-ink" : "text-muted"}>
              <span className={`mr-2 inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${done ? "bg-ok text-white" : "bg-line text-muted"}`} aria-hidden="true">{done ? "✓" : "•"}</span>
              {step.label}
            </li>
          );
        })}
      </ul>
      {morePages && (
        <p className="text-xs text-muted">
          You can continue now. We are still reading {job.phase2.pages_done} of {job.phase2.pages_total} more pages in the background to find your phone number and offers.
        </p>
      )}
    </div>
  );
}
