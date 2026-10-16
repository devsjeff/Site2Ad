"use client";

import React from "react";
import { normalizeUrl, qrUrlProblem, websiteSlotCount, type CreativePrefs, type ModeId } from "@/lib/creative";
import type { AssetInfo } from "@/lib/types";
import { InputField } from "../ui/InputField";
import { Toggle } from "../ui/Toggle";
import { ImageSelector } from "./ImageSelector";

interface PreferencesStepProps {
  mode: ModeId;
  prefs: CreativePrefs;
  onChange: (prefs: CreativePrefs) => void;
  websiteImages: string[];
  photos: AssetInfo[]; // auto: photos uploaded with the business details
  hasLogo: boolean;
  hasVideo: boolean; // manual: at least one uploaded video
  durationSeconds: number;
}

// The content switches. Only the switches that make sense for the chosen mode are shown, so no contradictory
// combination can be picked (the server checks again anyway).
export function PreferencesStep({ mode, prefs, onChange, websiteImages, photos, hasLogo, hasVideo, durationSeconds }: PreferencesStepProps) {
  const set = <K extends keyof CreativePrefs>(key: K, value: CreativePrefs[K]) => onChange({ ...prefs, [key]: value });
  const qrProblem = prefs.includeQr && prefs.qrUrl.trim() ? qrUrlProblem(prefs.qrUrl) : null;
  const slots = websiteSlotCount(durationSeconds);

  return (
    <div className="space-y-6">
      {mode === "website" && (
        <ImageSelector images={websiteImages} selected={prefs.selectedImageUrls} max={8} onChange={(v) => set("selectedImageUrls", v)}
          title="Website images in your ad"
          hint={`Each image plays for 3 seconds, so a ${durationSeconds}-second ad shows ${slots} image${slots === 1 ? "" : "s"}. With fewer images they repeat in a loop (one image fills the whole ad).`} />
      )}
      {mode === "mixed" && (
        <ImageSelector images={websiteImages} selected={prefs.selectedImageUrls} max={4} onChange={(v) => set("selectedImageUrls", v)}
          title="Opening and closing website images" hint="The first half opens the ad and the rest closes it, around the AI video. With one image it is used at both ends." />
      )}
      {mode === "ai" && (
        <div className="rounded-2xl border border-accent/25 bg-accent-soft/40 p-4 text-sm">
          <p className="font-medium text-ink">AI-generated footage only</p>
          <p className="mt-0.5 text-xs text-muted">No website pictures are used. The AI model creates the video from your scanned business details (services, offer, description). If it makes a shorter clip, the clip loops to your chosen length.</p>
        </div>
      )}

      {mode === "website" && photos.length > 0 && (
        <>
          <Toggle checked={prefs.useUploadedMedia} onChange={(v) => set("useUploadedMedia", v)} title={`Use my ${photos.length} uploaded photo${photos.length === 1 ? "" : "s"}`}
            help="Your photos play alongside the website images, 3 seconds each." />
          {prefs.useUploadedMedia && (
            <Toggle checked={prefs.preferWebsiteImages} onChange={(v) => set("preferWebsiteImages", v)} title="Website images first"
              help="On: original website images play before your uploaded photos. Off: your photos come first." />
          )}
        </>
      )}

      <Toggle checked={prefs.includeLogo} onChange={(v) => set("includeLogo", v)} title="Show my logo"
        help={hasLogo ? "Your uploaded logo is shown in the corner." : mode !== "manual" ? "Uses the logo found on your website, if there is a usable one." : "Upload a logo in the previous step to show it."} />

      <div className="space-y-3">
        <Toggle checked={prefs.includeQr} onChange={(v) => set("includeQr", v)} title="Add a QR code"
          help="A large, high-contrast QR code in the bottom-right corner. It opens exactly the address below." />
        {prefs.includeQr && (
          <InputField label="QR code opens" value={prefs.qrUrl} onChange={(v) => set("qrUrl", v)} placeholder="yourbusiness.com/menu" inputMode="url"
            error={qrProblem ?? undefined} helpText="Your own web address. Check it carefully: people will scan this." />
        )}
        {prefs.includeQr && prefs.qrUrl.trim() && normalizeUrl(prefs.qrUrl) !== prefs.qrUrl.trim() && (
          <button type="button" onClick={() => set("qrUrl", normalizeUrl(prefs.qrUrl))} className="text-xs font-medium text-accent hover:underline">
            Use {normalizeUrl(prefs.qrUrl)}
          </button>
        )}
      </div>

      {(hasVideo || mode === "ai" || mode === "mixed") && (
        <Toggle checked={prefs.keepAudio} onChange={(v) => set("keepAudio", v)} title="Keep the sound"
          help={hasVideo ? "Keeps the sound of your uploaded video. Turn off for screens that play silently." : "Keeps any sound the AI video provider returns. Turn off for a silent MP4."} />
      )}
    </div>
  );
}
