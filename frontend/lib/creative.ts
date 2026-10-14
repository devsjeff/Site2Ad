// Creative modes in the browser: sensible defaults per mode, one consistent request, and plain-language summaries.
// The backend (CreativeConfig in backend/app/schemas.py) re-validates everything; this file only keeps the UI honest.
// No runtime imports, so `node --test lib/creative.test.mjs` can load it directly.

import type { AdOptions, BusinessOverrides, CreativeConfig, GenerateAdRequest, HeroRef } from "./types";

export type ModeId = "manual" | "website" | "ai" | "mixed";

/** What the user can switch on and off in the settings step. Which switches are shown depends on the mode. */
export interface CreativePrefs {
  preferWebsiteImages: boolean; // website images before uploaded photos
  useUploadedMedia: boolean; // auto modes: also use the photos uploaded with the business details
  selectedImageUrls: string[]; // website images the user picked (empty = let the server pick the best ones)
  includeLogo: boolean;
  includeQr: boolean;
  qrUrl: string;
  keepAudio: boolean;
}

/** Everything needed to build the request for POST /api/generate-ad. */
export interface RequestInput {
  mode: ModeId;
  prefs: CreativePrefs;
  options: AdOptions;
  business: BusinessOverrides;
  jobId: string | null;
  hero: HeroRef | null;
  logoAssetId: string | null;
  mediaAssetIds: string[]; // manual: images and videos in play order; auto: uploaded photos
}

const SECURE_SCHEME = "https:";

/** True for the auto sub-modes that call the AI video provider. */
export function callsAiVideo(mode: ModeId): boolean {
  return mode === "ai" || mode === "mixed";
}

/** True when the mode reads the website scan. */
export function usesScan(mode: ModeId): boolean {
  return mode !== "manual";
}

/** True when the final video contains original website images (never in AI-only mode). */
export function showsWebsiteImages(mode: ModeId): boolean {
  return mode === "website" || mode === "mixed";
}

/** How many 3-second image slots a website-content ad of this length has (mirrors website_slots in services/ads.py). */
export function websiteSlotCount(durationSeconds: number): number {
  const full = Math.floor(durationSeconds / 3);
  const rest = durationSeconds - full * 3;
  if (full === 0) return 1;
  return full + (rest >= 1.5 ? 1 : 0);
}

/** Defaults for a mode. The QR code points at the user's own website when we know it. */
export function defaultPrefs(mode: ModeId, websiteUrl = ""): CreativePrefs {
  return {
    preferWebsiteImages: true,
    useUploadedMedia: mode === "manual",
    selectedImageUrls: [],
    includeLogo: true,
    includeQr: mode === "manual" || websiteUrl !== "",
    qrUrl: websiteUrl,
    keepAudio: true,
  };
}

/** Switch mode: keep the user's own choices (logo, QR, picked images) and reset only what the new mode decides. */
export function switchMode(prefs: CreativePrefs, mode: ModeId): CreativePrefs {
  return { ...prefs, useUploadedMedia: mode === "manual" ? true : prefs.useUploadedMedia };
}

/** Add the secure scheme when the user typed only a domain; everything else is kept exactly as typed. */
export function normalizeUrl(value: string): string {
  const url = value.trim();
  if (!url || /^[a-z][a-z0-9+.-]*:/i.test(url)) return url;
  return `${SECURE_SCHEME}//${url}`;
}

/** A QR destination the backend will accept: a public http(s) address with a domain (mirrors validate_destination_url). */
export function qrUrlProblem(value: string): string | null {
  const url = value.trim();
  if (!url) return "Enter the web address the QR code should open.";
  if (/\s/.test(url)) return "The address must not contain spaces.";
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "That is not a valid web address.";
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== SECURE_SCHEME) return "The address must start with http or https.";
  if (parsed.username || parsed.password) return "The address must not contain a user name or password.";
  const host = parsed.hostname.toLowerCase();
  const local = host === "localhost" || /\.(localhost|local|internal|lan)$/.test(host);
  const privateIp = /^(10\.|127\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|0\.)/.test(host) || host.startsWith("[");
  if (!host.includes(".") || local || privateIp) return "Use a public web address (not a local or private one).";
  return null;
}

/** The creative block of the request. Contradictory combinations cannot be produced from here. */
export function buildCreative(mode: ModeId, prefs: CreativePrefs, mediaAssetIds: string[]): CreativeConfig {
  const manual = mode === "manual";
  const websiteImages = showsWebsiteImages(mode);
  const uploads = manual ? mediaAssetIds : mode !== "ai" && prefs.useUploadedMedia ? mediaAssetIds : [];
  return {
    creation_mode: manual ? "manual" : "auto",
    creative_mode: manual ? null : mode,
    use_website_images: websiteImages,
    use_ai_video: callsAiVideo(mode),
    use_uploaded_media: uploads.length > 0,
    prefer_website_images: prefs.preferWebsiteImages,
    include_logo: prefs.includeLogo,
    include_qr: prefs.includeQr,
    qr_url: prefs.includeQr ? prefs.qrUrl.trim() : "",
    selected_image_urls: websiteImages ? [...prefs.selectedImageUrls] : [],
    media_asset_ids: [...uploads],
    keep_audio: prefs.keepAudio,
  };
}

/** The whole POST /api/generate-ad body for the chosen mode. */
export function buildRequest(input: RequestInput): GenerateAdRequest {
  const { mode } = input;
  return {
    job_id: usesScan(mode) ? input.jobId : null,
    business: input.business,
    options: input.options,
    hero: mode === "mixed" ? input.hero : null, // only Website + AI starts the AI video from a picture
    logo_asset_id: input.logoAssetId,
    photo_asset_ids: [],
    wait_for_prompt: false,
    creative: buildCreative(mode, input.prefs, input.mediaAssetIds),
  };
}

/** Problems that block "Create my ad", in plain language (empty = ready). */
export function readinessProblems(args: {
  mode: ModeId;
  prefs: CreativePrefs;
  mediaCount: number;
  websiteImageCount: number;
  aiAvailable: boolean;
  aiUnavailableReason: string;
  hasScan: boolean;
}): string[] {
  const { mode, prefs } = args;
  const problems: string[] = [];
  if (callsAiVideo(mode) && !args.aiAvailable) problems.push(args.aiUnavailableReason || "AI video generation is not available on this server.");
  if (mode === "manual" && args.mediaCount === 0) problems.push("Upload at least one image or video.");
  if ((mode === "website" || mode === "mixed") && !args.hasScan) problems.push("This mode needs a website scan. Scan your website first.");
  if (mode === "website" && args.websiteImageCount === 0 && !(prefs.useUploadedMedia && args.mediaCount > 0)) {
    problems.push("No website images are selected. Pick at least one, or upload photos.");
  }
  if (mode === "mixed" && args.websiteImageCount === 0) problems.push("Website + AI needs at least one website image for the opening and closing.");
  if (prefs.includeQr) {
    const problem = qrUrlProblem(prefs.qrUrl);
    if (problem) problems.push(`QR code: ${problem}`);
  }
  return problems;
}

/** The stages the server will run for a mode, in order (shown before creating). */
export function workflowStages(mode: ModeId): string[] {
  switch (mode) {
    case "manual":
      return ["Check and prepare your uploads", "Build the video with FFmpeg", "Add text, logo and QR code", "Check the finished MP4"];
    case "website":
      return ["Download your website images", "Show each image for 3 seconds (looping to your length)", "Add text, logo and QR code", "Check the finished MP4"];
    case "ai":
      return [
        "Write ONE detailed prompt from your scraped business details",
        "Generate AI footage (no website pictures)",
        "Loop the AI clip to your chosen length",
        "Add text, logo and QR code",
        "Check the finished MP4",
      ];
    case "mixed":
      return [
        "Download the opening and closing website images",
        "Write ONE detailed prompt from your scraped business details",
        "Generate the middle video with AI (looped to your length)",
        "Join website image → AI video → website image",
        "Add text, logo and QR code",
        "Check the finished MP4",
      ];
  }
}

/** Expected length in seconds, for the review step. */
export function estimatedSeconds(args: {
  mode: ModeId;
  durationSeconds: number;
  websiteImageSeconds: number;
  websiteImageCount: number;
  uploadedVideoSeconds: number;
  uploadedImageCount: number;
}): number {
  const { mode } = args;
  if (mode === "manual" && args.uploadedVideoSeconds > 0) return Math.round(args.uploadedVideoSeconds + 3 * args.uploadedImageCount);
  if (mode === "mixed") return args.durationSeconds + Math.min(4, Math.max(2, args.websiteImageCount)) * args.websiteImageSeconds;
  return args.durationSeconds;
}
