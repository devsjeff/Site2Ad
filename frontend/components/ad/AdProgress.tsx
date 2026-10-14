"use client";

import React, { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import type { AdResponse, AdStage } from "@/lib/types";
import { Button } from "../ui/Button";
import { ProgressBar } from "../ui/ProgressBar";
import { Spinner } from "../ui/Spinner";

const ORDER: AdStage[] = ["queued", "preparing", "prompt_building", "prompt_ready", "generating_video", "composing", "finalizing", "completed"];

// The stages this ad really runs, from the creative configuration it was created with.
function stepsFor(ad: AdResponse): { stage: AdStage; label: string }[] {
  const creative = ad.creative;
  if (creative && creative.creation_mode === "manual") {
    return [
      { stage: "preparing", label: "Preparing your uploads" },
      { stage: "composing", label: "Building the video with FFmpeg" },
      { stage: "finalizing", label: "Adding text, logo and QR code" },
    ];
  }
  if (creative && creative.creative_mode === "website") {
    return [
      { stage: "preparing", label: "Downloading your website images" },
      { stage: "composing", label: "Showing each image for 3 seconds" },
      { stage: "finalizing", label: "Adding text, logo and QR code" },
    ];
  }
  const mixed = creative !== null && creative.creative_mode === "mixed";
  return [
    { stage: "preparing", label: mixed ? "Preparing your website images" : "Collecting your business details" },
    { stage: "prompt_building", label: "Writing your ad prompt" },
    { stage: "generating_video", label: "Creating the AI video" },
    ...(creative ? [{ stage: "composing" as AdStage, label: mixed ? "Placing your website images around it" : "Looping it to your length" }] : []),
    { stage: "finalizing", label: "Adding your business details" },
  ];
}

// Progress bar and stage list while the ad is being made, with a way to stop it.
export function AdProgress({ ad }: { ad: AdResponse }) {
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const position = ORDER.indexOf(ad.stage);

  // Ask the server to stop this ad (the page keeps polling and shows the result).
  async function cancel() {
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelAd(ad.ad_id);
    } catch (error) {
      setCancelError(errorMessage(error));
      setCancelling(false);
    }
  }

  return (
    <div className="space-y-4 rounded-xl border border-line bg-surface p-5" aria-live="polite">
      <div className="flex items-center gap-3 text-sm font-medium text-ink">
        <Spinner />
        <span>{ad.message || "Working on your ad…"}</span>
      </div>
      <ProgressBar value={ad.progress} label="Ad progress" />
      <ul className="space-y-1.5 text-sm">
        {stepsFor(ad).map((step) => {
          const index = ORDER.indexOf(step.stage);
          const done = position > index || (step.stage === "prompt_building" && position >= ORDER.indexOf("prompt_ready"));
          const active = !done && position === index;
          return (
            <li key={step.stage} className={done ? "text-ink" : active ? "font-medium text-ink" : "text-muted"}>
              <span className="mr-2" aria-hidden="true">{done ? "✓" : active ? "▸" : "•"}</span>
              {step.label}
            </li>
          );
        })}
      </ul>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">You can leave this page open or come back to this link later.</p>
        <Button variant="secondary" onClick={cancel} loading={cancelling} className="px-4 py-2 text-xs">Cancel</Button>
      </div>
      {cancelError && <p className="text-xs text-danger">{cancelError}</p>}
    </div>
  );
}
