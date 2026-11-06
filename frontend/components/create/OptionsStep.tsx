"use client";

import React from "react";
import type { AdOptions, ConfigResponse } from "@/lib/types";
import { InputField } from "../ui/InputField";
import { OptionCard } from "../ui/OptionCard";
import { SelectField } from "../ui/SelectField";
import { Toggle } from "../ui/Toggle";

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
  part?: "all" | "essentials" | "advanced"; // essentials: format and length; advanced: everything optional
}

// Format, length (essentials) and goal, style, tone, creative instructions and the text overlay switch (advanced).
export function OptionsStep({
  config, options, onChange, durations = config.durations, durationNote, aiControls = true,
  overlayLabel = "Add my name, offer and contact details on the video", part = "all",
}: OptionsStepProps) {
  const set = <K extends keyof AdOptions>(key: K, value: AdOptions[K]) => onChange({ ...options, [key]: value });
  const essentials = part !== "advanced";
  const advanced = part !== "essentials";
  return (
    <div className="space-y-7">
      {essentials && (
        <>
          <section>
            <h3 className="mb-3 text-sm font-bold text-ink">Where will it play?</h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {config.platforms.map((platform) => (
                <OptionCard key={platform.id} compact icon={PLATFORM_ICONS[platform.id]} title={platform.label} description={platform.aspect_ratio} selected={options.platform === platform.id} onClick={() => set("platform", platform.id)} />
              ))}
            </div>
          </section>
          <section>
            <h3 className="mb-3 text-sm font-bold text-ink">Length</h3>
            <div className="inline-flex flex-wrap gap-1 rounded-2xl border border-line bg-surface/80 p-1" role="group" aria-label="Video length">
              {durations.map((seconds) => (
                <button key={seconds} type="button" aria-pressed={options.duration_seconds === seconds} onClick={() => set("duration_seconds", seconds)}
                  className={`rounded-xl px-5 py-2 text-sm font-bold transition-all duration-200 ${options.duration_seconds === seconds ? "bg-brand animate-gradient text-white shadow-glow" : "text-muted hover:bg-accent-soft hover:text-ink"}`}>
                  {seconds}s
                </button>
              ))}
            </div>
            {durationNote && <p className="mt-2 text-xs text-muted">{durationNote}</p>}
          </section>
          {config.voices.length > 0 && <section>
            <h3 className="mb-3 text-sm font-bold text-ink">Voice</h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {config.voices.filter((voice) => voice.engine !== "eleven" && (voice.languages ?? ["en"]).includes("en")).map((voice) => (
                <OptionCard key={voice.id} compact icon={voice.id === "none" ? "🔇" : "🎙️"} title={voice.label} description={voice.hint} selected={options.voice === voice.id} onClick={() => set("voice", voice.id)} />
              ))}
            </div>
            {config.voices.some((voice) => voice.engine === "eleven") && (
              <div className="mt-4">
                <p className="mb-2 text-xs font-bold uppercase tracking-widest text-muted">Studio-quality voices</p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {config.voices.filter((voice) => voice.engine === "eleven").map((voice) => (
                    <OptionCard key={voice.id} compact icon="🎧" title={voice.label.replace(" (ElevenLabs)", "")} description={voice.hint} badge="ElevenLabs" selected={options.voice === voice.id} onClick={() => set("voice", voice.id)} />
                  ))}
                </div>
              </div>
            )}
            <p className="mt-2 text-xs text-muted">
              {options.voice === "auto" ? "Auto picks the voice and music that suit your kind of business. " : ""}
              The voice speaks each on-screen line exactly when it appears.
              {options.platform === "taxi_screen" ? " Cab tablets are often silent, so your text carries the ad even without sound." : ""}
            </p>
          </section>}
          {config.music.length > 0 && <section>
            <h3 className="mb-3 text-sm font-bold text-ink">Music</h3>
            <div className="inline-flex flex-wrap gap-1 rounded-2xl border border-line bg-surface/80 p-1" role="group" aria-label="Background music">
              {config.music.map((track) => (
                <button key={track.id} type="button" aria-pressed={options.music === track.id} onClick={() => set("music", track.id)}
                  className={`rounded-xl px-4 py-2 text-sm font-bold transition-all duration-200 ${options.music === track.id ? "bg-brand animate-gradient text-white shadow-glow" : "text-muted hover:bg-accent-soft hover:text-ink"}`}>
                  {track.label}
                </button>
              ))}
            </div>
          </section>}
        </>
      )}
      {advanced && (
        <>
          {aiControls && options.ad_type === "auto" && (
            <section>
              <h3 className="mb-3 text-sm font-bold text-ink">What is the goal?</h3>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {config.goals.map((goal) => (
                  <OptionCard key={goal.id} compact icon={GOAL_ICONS[goal.id]} title={goal.label} selected={options.goal === goal.id} onClick={() => set("goal", goal.id)} />
                ))}
              </div>
            </section>
          )}
          <section className="grid gap-4 sm:grid-cols-2">
            <SelectField label="Look and feel" value={options.style} onChange={(v) => set("style", v || options.style)} options={config.styles.map((s) => ({ value: s.id, label: s.label }))} helpText={aiControls ? undefined : "Sets the speed of the motion over your images."} />
            {aiControls && <SelectField label="Tone" value={options.tone} onChange={(v) => set("tone", v || options.tone)} options={config.tones.map((t) => ({ value: t.id, label: t.label }))} />}
          </section>
          {(aiControls || options.ad_type !== "auto") && (
            <InputField label="Creative instructions (optional)" multiline value={options.special_instructions} onChange={(v) => set("special_instructions", v)} maxLength={600} placeholder="e.g. Show the gift boxes on a festive table" helpText={'Short hints for the ad, e.g. the occasion (Diwali) or a real customer quote in "double quotes". Do not put phone numbers or prices here; use the business details instead.'} />
          )}
          <Toggle checked={options.add_overlays} onChange={(v) => set("add_overlays", v)} title={overlayLabel} help="Added as clean, animated text after the video is made, so spelling and numbers are always correct." />
        </>
      )}
    </div>
  );
}
