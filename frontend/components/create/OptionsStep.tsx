"use client";

import React from "react";
import type { AdOptions, ConfigResponse } from "@/lib/types";
import { InputField } from "../ui/InputField";
import { OptionCard } from "../ui/OptionCard";
import { SelectField } from "../ui/SelectField";

const PLATFORM_ICONS: Record<string, string> = { taxi_screen: "🚕", instagram_reel: "📸", youtube_shorts: "▶️", facebook_feed: "👍" };
const GOAL_ICONS: Record<string, string> = { awareness: "📢", offer: "🏷️", visits: "📍", event: "🎪", product: "🚀" };

interface OptionsStepProps {
  config: ConfigResponse;
  options: AdOptions;
  onChange: (options: AdOptions) => void;
  durations?: number[];
  durationNote?: string;
  aiControls?: boolean; // goal, tone and creative instructions only matter to the AI prompt writer
  overlayLabel?: string;
}

// Format, goal, style, tone, length, creative instructions and the text overlay switch.
export function OptionsStep({
  config, options, onChange, durations = config.durations, durationNote, aiControls = true,
  overlayLabel = "Add my name, offer and contact details on the video",
}: OptionsStepProps) {
  const set = <K extends keyof AdOptions>(key: K, value: AdOptions[K]) => onChange({ ...options, [key]: value });
  return (
    <div className="space-y-8">
      <section>
        <h3 className="mb-3 text-sm font-semibold text-ink">Where will it play?</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {config.platforms.map((platform) => (
            <OptionCard key={platform.id} icon={PLATFORM_ICONS[platform.id]} title={platform.label} description={platform.aspect_ratio} selected={options.platform === platform.id} onClick={() => set("platform", platform.id)} />
          ))}
        </div>
      </section>
      {aiControls && (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-ink">What is the goal?</h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {config.goals.map((goal) => (
              <OptionCard key={goal.id} icon={GOAL_ICONS[goal.id]} title={goal.label} selected={options.goal === goal.id} onClick={() => set("goal", goal.id)} />
            ))}
          </div>
        </section>
      )}
      <section className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Look and feel" value={options.style} onChange={(v) => set("style", v || options.style)} options={config.styles.map((s) => ({ value: s.id, label: s.label }))} helpText={aiControls ? undefined : "Sets the speed of the motion over your images."} />
        {aiControls && <SelectField label="Tone" value={options.tone} onChange={(v) => set("tone", v || options.tone)} options={config.tones.map((t) => ({ value: t.id, label: t.label }))} />}
      </section>
      <section>
        <h3 className="mb-3 text-sm font-semibold text-ink">Length</h3>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Video length">
          {durations.map((seconds) => (
            <button key={seconds} type="button" aria-pressed={options.duration_seconds === seconds} onClick={() => set("duration_seconds", seconds)} className={`rounded-lg border-2 px-4 py-2 text-sm font-medium transition-colors ${options.duration_seconds === seconds ? "border-accent bg-accent-soft text-ink" : "border-line bg-surface text-muted hover:border-accent/60"}`}>
              {seconds} seconds
            </button>
          ))}
        </div>
        {durationNote && <p className="mt-2 text-xs text-muted">{durationNote}</p>}
      </section>
      {aiControls && (
        <InputField label="Creative instructions (optional)" multiline value={options.special_instructions} onChange={(v) => set("special_instructions", v)} maxLength={600} placeholder="e.g. Show the gift boxes on a festive table" helpText="Short hints for the AI prompt writer. Do not put phone numbers or prices here; use the business details instead." />
      )}
      <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-surface p-4 text-sm">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={options.add_overlays} onChange={(e) => set("add_overlays", e.target.checked)} />
        <span>
          <span className="font-medium text-ink">{overlayLabel}</span>
          <span className="mt-0.5 block text-xs text-muted">Added as clean text after the video is made, so spelling and numbers are always correct.</span>
        </span>
      </label>
    </div>
  );
}
