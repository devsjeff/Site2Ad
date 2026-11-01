"use client";

import React from "react";
import { callsAiVideo, workflowStages, type CreativePrefs, type ModeId } from "@/lib/creative";
import type { AdOptions, ConfigResponse } from "@/lib/types";
import { Alert } from "../ui/Alert";

export type EditTarget = "mode" | "business" | "creative" | "settings";

export interface ReviewSummary {
  name: string;
  offer: string;
  cta: string;
  phone: string;
  address: string;
  media: string[]; // one line per source, e.g. "3 original website images"
  logo: string;
  estimatedSeconds: number;
}

interface ReviewStepProps {
  config: ConfigResponse;
  mode: ModeId;
  prefs: CreativePrefs;
  options: AdOptions;
  summary: ReviewSummary;
  problems: string[];
  onEdit: (target: EditTarget) => void;
}

// One label / value line in the review summary.
function Row({ label, value, missing }: { label: string; value: string; missing?: string }) {
  return (
    <div className="flex gap-4 py-2 text-sm">
      <dt className="w-32 shrink-0 text-muted">{label}</dt>
      <dd className={value ? "text-ink" : "text-muted italic"}>{value || missing || "Not set"}</dd>
    </div>
  );
}

// A titled box with an Edit link.
function Card({ title, onEdit, children }: { title: string; onEdit?: () => void; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-surface/85 p-5">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-bold text-ink">{title}</h3>
        {onEdit && <button type="button" onClick={onEdit} className="rounded-full bg-accent-soft px-3 py-1 text-xs font-bold text-accent transition-colors hover:bg-accent hover:text-white">Edit</button>}
      </div>
      {children}
    </div>
  );
}

// Everything the server will do, before anything is created.
export function ReviewStep({ config, mode, prefs, options, summary, problems, onEdit }: ReviewStepProps) {
  const label = (list: { id: string; label: string }[], id: string) => list.find((item) => item.id === id)?.label ?? id;
  const modeInfo = config.creative_modes.find((m) => m.id === mode);
  const ai = callsAiVideo(mode);
  const platform = config.platforms.find((p) => p.id === options.platform);
  const textOn = options.add_overlays;
  return (
    <div className="space-y-6">
      <Card title="How it is made" onEdit={() => onEdit(mode === "manual" ? "mode" : "creative")}>
        <dl className="divide-y divide-line">
          <Row label="Mode" value={mode === "manual" ? "Manual ad" : `Auto ad · ${modeInfo?.label ?? mode}`} />
          <Row label="AI video provider" value={ai ? `Will be called (${config.video_provider})` : "Not called: built with FFmpeg only"} />
          <Row label="Website scan" value={mode === "manual" ? "Not used" : mode === "ai" ? "Business details only (no website pictures)" : "Business details and original images"} />
          {ai && <Row label="Prompt writer" value={config.prompt_builder === "llm" ? "AI prompt writer, checked against your facts" : "Built-in prompt writer"} />}
        </dl>
      </Card>

      <Card title="Media" onEdit={() => onEdit(mode === "manual" ? "business" : "settings")}>
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
          {summary.media.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </Card>

      <Card title="Format and details" onEdit={() => onEdit("settings")}>
        <dl className="divide-y divide-line">
          <Row label="Format" value={platform ? `${platform.label} (${platform.aspect_ratio})` : options.platform} />
          <Row label="Length" value={`About ${summary.estimatedSeconds} seconds`} />
          <Row label="Style" value={label(config.styles, options.style)} />
          {config.ad_types.length > 0 && <Row label="Kind of ad" value={label(config.ad_types, options.ad_type)} />}
          {config.voices.length > 0 && <Row label="Sound" value={[options.voice !== "none" ? `${label(config.voices, options.voice)} voice` : "", options.music !== "none" ? `${label(config.music, options.music)} music` : ""].filter(Boolean).join(" with ")} missing="Silent" />}
          <Row label="QR code" value={prefs.includeQr ? `Opens ${prefs.qrUrl.trim()}` : ""} missing="No QR code" />
          <Row label="Logo" value={prefs.includeLogo ? summary.logo : ""} missing="No logo" />
          <Row label="Business name" value={textOn ? summary.name : ""} missing={textOn ? "None" : "Text overlays are off"} />
          <Row label="Offer" value={textOn ? summary.offer : ""} missing={textOn ? "None" : "—"} />
          <Row label="Call to action" value={textOn ? summary.cta : ""} missing={textOn ? "None" : "—"} />
          {textOn && (summary.phone || summary.address) && <Row label="Contact" value={[summary.phone, summary.address].filter(Boolean).join(" · ")} />}
        </dl>
      </Card>

      <Card title="What will happen">
        <ol className="list-decimal space-y-1 pl-5 text-sm text-ink">
          {workflowStages(mode).map((stage) => <li key={stage}>{stage}</li>)}
        </ol>
        <p className="mt-3 text-xs text-muted">
          {ai ? "Creating the AI video usually takes 1 to 3 minutes. If the provider fails, you are told clearly; a replacement clip is never presented as AI footage." : "FFmpeg ads are usually ready in under a minute."}
        </p>
      </Card>

      {problems.length > 0 && (
        <Alert tone="warn" title="Before you create">
          <ul className="list-disc space-y-1 pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Alert>
      )}
    </div>
  );
}
