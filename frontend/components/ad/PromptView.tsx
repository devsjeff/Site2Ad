"use client";

import React, { useState } from "react";
import type { AdPrompt } from "@/lib/types";

// Shows the exact prompt that was used, with a copy button.
export function PromptView({ prompt }: { prompt: AdPrompt }) {
  const [copied, setCopied] = useState(false);

  // Copy the prompt to the clipboard.
  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt.final_prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <details className="rounded-xl border border-line bg-surface p-4 text-sm">
      <summary className="cursor-pointer font-medium text-ink">
        The prompt behind this ad
        <span className="ml-2 text-xs font-normal text-muted">
          {prompt.shot_count} shots, {prompt.duration_seconds} seconds, {prompt.aspect_ratio}, written by {prompt.builder === "llm" ? "AI" : "the built-in writer"}
        </span>
      </summary>
      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-background p-3 font-mono text-xs leading-relaxed text-ink">{prompt.final_prompt}</pre>
      <div className="mt-3 flex items-center justify-between text-xs text-muted">
        <span>{prompt.reference_image ? "Starts from your chosen image." : "No starting image was used."}</span>
        <button type="button" onClick={copy} className="font-medium text-accent hover:underline">{copied ? "Copied" : "Copy prompt"}</button>
      </div>
    </details>
  );
}
