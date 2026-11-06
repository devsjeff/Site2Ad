import React from "react";
import { STEP_LABELS, type FlowStep } from "@/lib/flow";

// Where you are in the flow: one dot per screen of the path you chose, and the name of the current one.
export function StepDots({ steps, current }: { steps: FlowStep[]; current: FlowStep }) {
  const index = Math.max(0, steps.indexOf(current));
  return (
    <div className="mt-3 flex shrink-0 flex-col items-end gap-1.5" aria-label={`Step ${index + 1} of ${steps.length}: ${STEP_LABELS[current]}`}>
      <div className="flex items-center gap-1.5">
        {steps.map((key, position) => (
          <span key={key} className={`h-2 rounded-full transition-all duration-500 ${key === current ? "bg-brand w-7" : position < index ? "w-2 bg-accent" : "w-2 bg-line"}`} />
        ))}
      </div>
      <span className="text-[11px] font-semibold uppercase tracking-widest text-muted">{index + 1}/{steps.length} · {STEP_LABELS[current]}</span>
    </div>
  );
}
