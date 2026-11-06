"use client";

import React from "react";
import type { BuildStyle } from "@/lib/flow";
import { Alert } from "../ui/Alert";

interface BuildStyleStepProps {
  value: BuildStyle;
  onChange: (style: BuildStyle) => void;
  studioAvailable: boolean;
  studioMessage: string;
}

const CHOICES: { style: BuildStyle; icon: string; title: string; badge: string; time: string; text: string; points: string[] }[] = [
  {
    style: "captions", icon: "⚡", title: "Caption + QR", badge: "Fast", time: "About 1 to 2 minutes",
    text: "Your website pictures with gentle motion, animated captions, your offer and logo, and a QR code.",
    points: ["Pick the kind of ad, platform, length and sound", "QR code and logo on the video", "Ready in a minute or two"],
  },
  {
    style: "studio", icon: "🎞️", title: "Studio", badge: "Best result · takes longer", time: "About 3 to 5 minutes",
    text: "A designed, story-driven video built from what your website really says.",
    points: ["A plan you approve first (message, voice, music)", "Brand colours and fonts, voice-over in your language, sound effects", "Every number and claim checked against your website"],
  },
];

// Two ways to build the ad from the website: quick captions with a QR code, or the slower, more designed Studio video.
export function BuildStyleStep({ value, onChange, studioAvailable, studioMessage }: BuildStyleStepProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2" role="group" aria-label="How should the ad be built?">
        {CHOICES.map((choice) => {
          const disabled = choice.style === "studio" && !studioAvailable;
          const selected = value === choice.style && !disabled;
          return (
            <button key={choice.style} type="button" aria-pressed={selected} disabled={disabled} onClick={() => onChange(choice.style)}
              className={`group relative flex flex-col rounded-3xl border-2 p-6 text-left transition-all duration-300 ${
                disabled ? "cursor-not-allowed border-line bg-surface/60 opacity-60" : `hover:-translate-y-1 hover:shadow-glow ${selected ? "ring-brand shadow-glow" : "border-line bg-surface/85 hover:border-accent/50"}`}`}>
              {selected && <span className="bg-brand animate-popIn absolute right-4 top-4 flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold text-white" aria-hidden="true">✓</span>}
              <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-2xl transition-transform group-hover:scale-110 group-hover:-rotate-6" aria-hidden="true">{choice.icon}</span>
              <span className="pr-8 text-lg font-extrabold text-ink">{choice.title}</span>
              <span className={`mt-1 inline-flex w-fit rounded-full px-2.5 py-0.5 text-xs font-bold ${choice.style === "studio" ? "bg-brand text-white" : "bg-accent-soft text-ink"}`}>{choice.badge}</span>
              <span className="mt-3 text-sm leading-relaxed text-muted">{choice.text}</span>
              <ul className="mt-3 space-y-1.5 text-sm text-ink">
                {choice.points.map((point) => <li key={point} className="flex items-start gap-2"><span className="mt-0.5 text-ok" aria-hidden="true">✓</span>{point}</li>)}
              </ul>
              <span className="mt-4 text-xs font-semibold text-muted">⏱ {choice.time}</span>
            </button>
          );
        })}
      </div>
      {!studioAvailable && <Alert tone="warn" title="Studio is not set up on this server">{studioMessage}</Alert>}
    </div>
  );
}
