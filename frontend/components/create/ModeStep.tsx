"use client";

import React from "react";
import type { CreationMode, CreativeModeInfo } from "@/lib/types";
import { OptionCard } from "../ui/OptionCard";

const AUTO_DESCRIPTION = "Enter your website address. We read it, then you choose: original website content, an AI-generated video, or a mix of both.";

interface ModeStepProps {
  modes: CreativeModeInfo[];
  value: CreationMode | null;
  onChange: (mode: CreationMode) => void;
}

// Manual ad (your own media) or auto ad (from your website).
export function ModeStep({ modes, value, onChange }: ModeStepProps) {
  const manual = modes.find((mode) => mode.id === "manual");
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <OptionCard
        icon="✨"
        title="Auto ad"
        description={AUTO_DESCRIPTION}
        badge="From your website"
        selected={value === "auto"}
        onClick={() => onChange("auto")}
      />
      <OptionCard
        icon="🎬"
        title={manual?.label ?? "Manual ad"}
        description={manual?.description}
        badge="Your uploads · FFmpeg only · no AI video"
        selected={value === "manual"}
        onClick={() => onChange("manual")}
      />
    </div>
  );
}
