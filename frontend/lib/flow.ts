// The steps of the one "Make an ad" flow, and which of them a choice leads through (no React, no network, so it can be tested on its own).
//
//   Manual:     type → media (own photos or videos) → settings → review
//   Automated:  type → media (website pictures, full AI or a mix, plus the website scan)
//                 → style (Caption + QR, or Studio) → settings → review          (Caption + QR)
//                 → style → Studio screens (type of video, plan, build, result)   (Studio)
//   Studio is built from the website's own pictures and claims, so it is offered only when the media comes from the website.

import type { CreationMode, CreativeMode } from "./types";

export type FlowStep = "how" | "media" | "style" | "customize" | "review" | "studio";
export type BuildStyle = "captions" | "studio";

export const STEP_LABELS: Record<FlowStep, string> = {
  how: "Type", media: "Media", style: "Style", customize: "Settings", review: "Review", studio: "Studio",
};

/** Studio needs the website's own pictures and wording, so only "media from my website" can use it. */
export function studioAllowed(creation: CreationMode | null, source: CreativeMode | null): boolean {
  return creation === "auto" && source === "website";
}

/** The style that really applies: Studio falls back to Caption + QR when the media is not from the website. */
export function effectiveStyle(creation: CreationMode | null, source: CreativeMode | null, style: BuildStyle): BuildStyle {
  return style === "studio" && studioAllowed(creation, source) ? "studio" : "captions";
}

/** The screens of the flow for these choices, in order. */
export function flowSteps(creation: CreationMode | null, source: CreativeMode | null, style: BuildStyle): FlowStep[] {
  if (studioAllowed(creation, source)) {
    return effectiveStyle(creation, source, style) === "studio" ? ["how", "media", "style", "studio"] : ["how", "media", "style", "customize", "review"];
  }
  return ["how", "media", "customize", "review"];
}

export function stepAfter(steps: FlowStep[], current: FlowStep): FlowStep {
  const index = steps.indexOf(current);
  return steps[Math.min(steps.length - 1, index < 0 ? 0 : index + 1)];
}

export function stepBefore(steps: FlowStep[], current: FlowStep): FlowStep {
  const index = steps.indexOf(current);
  return steps[Math.max(0, index < 0 ? 0 : index - 1)];
}

/** What the address asks for: /ads/create?mode=manual|auto, ?style=studio, ?studio=<job id>, ?job=<scan id>. The first screen to show, and the choices behind it. */
export interface Deeplink {
  creation: CreationMode | null;
  source: CreativeMode | null;
  style: BuildStyle;
  step: FlowStep;
  scanJob: string | null;
  studioJob: string | null;
}

const JOB_ID = /^[0-9a-f]{32}$/;

export function readDeeplink(search: string): Deeplink {
  const params = new URLSearchParams(search);
  const studioJob = params.get("studio") ?? "";
  const scanJob = params.get("job") ?? "";
  const mode = params.get("mode");
  if (JOB_ID.test(studioJob)) return { creation: "auto", source: "website", style: "studio", step: "studio", scanJob: null, studioJob };
  if (JOB_ID.test(scanJob)) return { creation: "auto", source: null, style: "captions", step: "media", scanJob, studioJob: null };
  if (params.get("style") === "studio") return { creation: "auto", source: "website", style: "studio", step: "media", scanJob: null, studioJob: null };
  if (mode === "manual" || mode === "auto") return { creation: mode, source: null, style: "captions", step: "media", scanJob: null, studioJob: null };
  return { creation: null, source: null, style: "captions", step: "how", scanJob: null, studioJob: null };
}
