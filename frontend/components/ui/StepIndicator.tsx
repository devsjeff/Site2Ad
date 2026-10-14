import React from "react";

// Row of numbered steps with the current one highlighted.
export function StepIndicator({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex w-full items-center" aria-label="Progress">
      {steps.map((title, index) => {
        const number = index + 1;
        const done = number < current;
        const active = number === current;
        return (
          <React.Fragment key={title}>
            <li className="flex flex-col items-center gap-2" aria-current={active ? "step" : undefined}>
              <span
                className={`flex h-9 w-9 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors ${
                  done ? "border-accent bg-accent text-white" : active ? "border-accent bg-accent-soft text-accent" : "border-line bg-surface text-muted"
                }`}
              >
                {done ? "✓" : number}
              </span>
              <span className={`whitespace-nowrap text-xs font-medium sm:text-sm ${number <= current ? "text-ink" : "text-muted"}`}>{title}</span>
            </li>
            {index < steps.length - 1 && (
              <li aria-hidden="true" className="mt-[-1.4rem] flex-1 px-2 sm:px-4">
                <div className={`h-1 w-full rounded ${done ? "bg-accent" : "bg-line"}`} />
              </li>
            )}
          </React.Fragment>
        );
      })}
    </ol>
  );
}
