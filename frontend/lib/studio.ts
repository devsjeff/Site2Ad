// Small helpers for the Studio screens (no network, no React) so they can be tested on their own.

import type { ConfigOption, StudioPlatform, StudioStatus, StudioVideoType } from "./types";

export const TYPE_ICONS: Record<StudioVideoType, string> = {
  promo: "🏷️", hook_ad: "🎣", pitch: "🚀", showcase: "🖼️", explainer: "🧭", testimonial: "💬", launch: "🎉",
};

export const STAGE_ICONS: Record<string, string> = {
  capture: "📸", notes: "📝", brand: "🎨", assumptions: "🧭", storyboard: "🎬", build: "🎞️", check: "✅",
};

export const PLATFORM_CHOICES: { id: StudioPlatform; label: string; hint: string; w: number; h: number }[] = [
  { id: "16:9", label: "Landscape", hint: "Cab screens, YouTube", w: 32, h: 18 },
  { id: "9:16", label: "Vertical", hint: "Reels, Shorts, Stories", w: 18, h: 32 },
  { id: "1:1", label: "Square", hint: "Feed posts", w: 24, h: 24 },
];

const LENGTHS = [10, 15, 20, 30, 45, 60];

/** The lengths a video type allows: each shot needs about two seconds to be read, so short lengths are not offered for long structures. */
export function lengthChoices(minLength: number): number[] {
  return LENGTHS.filter((seconds) => seconds >= minLength);
}

/** Keep the chosen length valid when the video type changes (the nearest allowed length at or above the minimum). */
export function fitLength(length: number, minLength: number): number {
  const choices = lengthChoices(minLength);
  return choices.includes(length) ? length : choices[0] ?? Math.max(length, minLength);
}

/** Lines of a text area as a list: trimmed, no blanks, no duplicates, at most `limit`. */
export function splitLines(text: string, limit = 5): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (line && !seen.has(line.toLowerCase())) {
      seen.add(line.toLowerCase());
      out.push(line);
    }
  }
  return out.slice(0, limit);
}

export function isWorking(status: StudioStatus): boolean {
  return status === "queued" || status === "running";
}

/** Statuses at which polling can stop (the person has to act, or the job is over). */
export function stopsPolling(status: StudioStatus): boolean {
  return status === "review" || status === "completed" || status === "failed" || status === "cancelled";
}

/** "bg-..." aspect classes for the video player by platform. */
export function playerShape(platform: StudioPlatform): string {
  return platform === "9:16" ? "mx-auto max-w-xs aspect-[9/16]" : platform === "1:1" ? "mx-auto max-w-md aspect-square" : "w-full aspect-video";
}

/** "20 to 45 s": seconds as the screens show them. */
export function seconds(value: number): string {
  return `${Number.isInteger(value) ? value : value.toFixed(1)} s`;
}

/** Voices that speak `language` (the pseudo voices "auto" and "none" are the screens' own choices), free ones first. */
export function voicesFor(voices: ConfigOption[], language: string): ConfigOption[] {
  const speaking = voices.filter((v) => v.id !== "auto" && v.id !== "none" && (v.languages ?? ["en"]).includes(language));
  return [...speaking.filter((v) => v.engine !== "eleven"), ...speaking.filter((v) => v.engine === "eleven")];
}

/** The voice to use after the language changed: the same one when it speaks the new language, else "auto" (or the first voice when `allowAuto` is false). */
export function voiceAfterLanguage(voices: ConfigOption[], language: string, current: string, allowAuto = true): string {
  if (current === "none" || (current === "auto" && allowAuto)) return current;
  const fits = voicesFor(voices, language);
  if (fits.some((v) => v.id === current)) return current;
  return allowAuto ? "auto" : fits[0]?.id ?? current;
}

/** "Hindi (हिन्दी)", or just "English" when the name is the same. */
export function languageLabel(language: ConfigOption): string {
  return language.native && language.native !== language.label ? `${language.label} (${language.native})` : language.label;
}
