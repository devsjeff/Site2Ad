"use client";

import React from "react";
import type { CreativeMode, CreativeModeInfo } from "@/lib/types";
import { Alert } from "../ui/Alert";
import { OptionCard } from "../ui/OptionCard";

const ICONS: Record<string, string> = { website: "🖼️", ai: "🤖", mixed: "🧩" };

// Short card copy; the server's longer description is the fallback for unknown modes.
const SHORT: Record<string, string> = {
  website: "Your own website photos, 3 seconds each, with motion, text and QR code.",
  ai: "A brand-new AI video made from your business details. No website photos.",
  mixed: "Website photos open and close the ad around an AI video clip.",
};

interface CreativeModeStepProps {
  modes: CreativeModeInfo[];
  value: CreativeMode | null;
  onChange: (mode: CreativeMode) => void;
  aiMessage: string;
  aiAvailable: boolean;
}

// What the server will run for this card, in a few words.
function badgeFor(mode: CreativeModeInfo): string {
  if (!mode.uses_ai_video) return "No AI video · FFmpeg only";
  return mode.id === "ai" ? "AI footage only · no website pictures" : "Website pictures + AI video";
}

// The three auto creative modes, as offered by the server (GET /api/config).
export function CreativeModeStep({ modes, value, onChange, aiMessage, aiAvailable }: CreativeModeStepProps) {
  const auto = modes.filter((mode) => mode.creation_mode === "auto");
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        {auto.map((mode) => (
          <OptionCard
            key={mode.id}
            icon={ICONS[mode.id]}
            title={mode.label}
            description={SHORT[mode.id] ?? mode.description}
            badge={badgeFor(mode)}
            note={mode.available ? undefined : "Not available on this server"}
            disabled={!mode.available}
            selected={value === mode.id}
            onClick={() => onChange(mode.id as CreativeMode)}
          />
        ))}
      </div>
      {!aiAvailable && (
        <Alert tone="warn" title="AI video is not available">
          {aiMessage} Website Content Priority still works, and it never calls an AI video service.
        </Alert>
      )}
    </div>
  );
}
