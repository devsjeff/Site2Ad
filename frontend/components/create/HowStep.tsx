"use client";

import React from "react";
import type { CreationMode } from "@/lib/types";

interface HowStepProps {
  onChoose: (mode: CreationMode) => void;
}

const CHOICES: { mode: CreationMode; icon: string; title: string; tag: string; text: string; points: string[]; tint: string }[] = [
  {
    mode: "manual", icon: "🎬", title: "Manual", tag: "I have my own photos or videos",
    text: "Upload your media, add your name, offer, logo and a QR code. Nothing is scanned or generated.",
    points: ["Your own photos and videos", "Quickest way to a finished ad", "No AI video"], tint: "from-amber-400/25 via-pink-500/10 to-transparent",
  },
  {
    mode: "auto", icon: "✨", title: "Automated", tag: "Start from my website",
    text: "We read your website and build the ad for you. Use its pictures, an AI-made video, or a mix of both.",
    points: ["Website pictures, full AI or a mix", "Caption + QR, or the designed Studio video", "Your name, offer and details found for you"], tint: "from-violet-500/25 via-fuchsia-500/10 to-transparent",
  },
];

// The first screen: are you giving the media yourself, or should it be made from your website?
export function HowStep({ onChoose }: HowStepProps) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {CHOICES.map((choice, index) => (
        <li key={choice.mode} className={`animate-fadeUp delay-${index + 1}`}>
          <button type="button" onClick={() => onChoose(choice.mode)}
            className="group relative flex h-full w-full flex-col overflow-hidden rounded-3xl border-2 border-line bg-surface/85 p-6 text-left transition-all duration-300 hover:-translate-y-1 hover:border-accent/60 hover:shadow-glow focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/25">
            <div className={`absolute inset-0 bg-gradient-to-br ${choice.tint} opacity-60 transition-opacity group-hover:opacity-100`} aria-hidden="true" />
            <span className="relative mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface text-3xl shadow-sm transition-transform group-hover:scale-110 group-hover:-rotate-6" aria-hidden="true">{choice.icon}</span>
            <span className="relative text-xl font-extrabold text-ink">{choice.title}</span>
            <span className="relative mt-0.5 text-sm font-semibold text-accent">{choice.tag}</span>
            <span className="relative mt-3 text-sm leading-relaxed text-muted">{choice.text}</span>
            <ul className="relative mt-4 space-y-1.5 text-sm text-ink">
              {choice.points.map((point) => (
                <li key={point} className="flex items-start gap-2"><span className="mt-0.5 text-ok" aria-hidden="true">✓</span>{point}</li>
              ))}
            </ul>
            <span className="relative mt-5 text-sm font-bold text-accent transition-transform group-hover:translate-x-1">Choose {choice.title.toLowerCase()} →</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
