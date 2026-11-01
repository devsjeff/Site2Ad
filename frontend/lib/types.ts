// Types mirror backend/app/schemas.py. `scripts/check_contract.py` fails the build when a field here is missing there.

export type ScrapeStatus =
  | "ok" | "partial" | "blocked" | "unreachable" | "invalid_url" | "unsupported_platform" | "timeout" | "internal_error";
export type JobStatus = "queued" | "running" | ScrapeStatus;
export type ScrapeStage = "queued" | "fetching" | "rendering" | "extracting" | "ad_ready";
export type AdStatus = "queued" | "running" | "completed" | "completed_with_fallback" | "failed";
export type AdStage =
  | "queued" | "preparing" | "prompt_building" | "prompt_ready" | "generating_video" | "composing" | "finalizing" | "completed" | "failed";
export type CreationMode = "manual" | "auto";
export type CreativeMode = "website" | "ai" | "mixed";
export type SegmentKind = "website_image" | "uploaded_image" | "uploaded_video" | "ai_video" | "fallback_video";

export interface Phone {
  number: string;
  display: string;
  source: string;
}

export interface SiteInfo {
  name: string;
  title: string;
  description: string;
  language: string;
  logo: string;
  favicon: string;
  phone: string;
  phones: Phone[];
  address: string;
  category: string;
  services: string[];
  offer: string;
  cta: string;
  brand_colors: string[];
  text_excerpt: string;
}

export interface Contacts {
  whatsapp: string[];
  emails: string[];
  social: string[];
}

export interface PageInfo {
  url: string;
  title: string;
  description: string;
  text_excerpt: string;
  kind: string;
  rendered_with: "httpx" | "playwright";
}

export interface ScrapeMeta {
  rendered_with: "httpx" | "playwright";
  bot_protection: string | null;
  csr_score: number;
  embedded_data: boolean;
  took_ms: number;
  phase: number;
  browser: string | null;
}

export interface ScrapeResult {
  schema_version: number;
  status: ScrapeStatus;
  message: string;
  final_url: string;
  home_url: string;
  site: SiteInfo;
  images: string[];
  contacts: Contacts;
  pages: PageInfo[];
  meta: ScrapeMeta;
  flags: string[];
}

export interface Phase2Info {
  state: "pending" | "running" | "done" | "skipped" | "failed";
  pages_done: number;
  pages_total: number;
}

export interface JobResponse {
  job_id: string;
  url: string;
  status: JobStatus;
  stage: ScrapeStage;
  progress: number;
  message: string;
  cached: boolean;
  is_final: boolean;
  phase2: Phase2Info;
  result: ScrapeResult | null;
  created_at: string;
  updated_at: string;
}

export interface AssetInfo {
  asset_id: string;
  kind: "logo" | "photo" | "video";
  url: string;
  filename: string;
  width: number;
  height: number;
  bytes: number;
  media_type: "image" | "video";
  duration_seconds: number;
  has_audio: boolean;
}

export interface UploadResponse {
  assets: AssetInfo[];
}

export interface AdOptions {
  goal: string;
  ad_type: string;
  voice: string;
  music: string;
  platform: string;
  duration_seconds: number;
  style: string;
  tone: string;
  special_instructions: string;
  add_overlays: boolean;
}

export interface BusinessOverrides {
  name: string;
  website_url: string;
  category: string;
  description: string;
  phone: string;
  address: string;
  offer: string;
  cta: string;
  services: string[];
  omit: string[];
}

export interface HeroRef {
  source: "scraped" | "asset";
  url?: string | null;
  asset_id?: string | null;
}

/** How ONE ad is made. The backend re-validates every combination (backend/app/schemas.py CreativeConfig). */
export interface CreativeConfig {
  creation_mode: CreationMode;
  creative_mode: CreativeMode | null;
  use_website_images: boolean;
  use_ai_video: boolean;
  use_uploaded_media: boolean;
  prefer_website_images: boolean;
  include_logo: boolean;
  include_qr: boolean;
  qr_url: string;
  selected_image_urls: string[];
  media_asset_ids: string[];
  keep_audio: boolean;
}

export interface GenerateAdRequest {
  job_id?: string | null;
  scrape_result?: ScrapeResult | null;
  business: BusinessOverrides;
  options: AdOptions;
  hero?: HeroRef | null;
  logo_asset_id?: string | null;
  photo_asset_ids: string[];
  wait_for_prompt: boolean;
  creative?: CreativeConfig | null;
}

export interface ReferenceImage {
  source: "scraped" | "asset";
  url: string | null;
  asset_id: string | null;
  role: "first_frame";
  width: number;
  height: number;
}

export interface AdPrompt {
  final_prompt: string;
  positive_prompt: string;
  negative_prompt: string;
  platform: string;
  duration_seconds: number;
  aspect_ratio: string;
  shot_count: number;
  builder: "llm" | "template";
  model: string;
  reference_image: ReferenceImage | null;
  warnings: string[];
}

export interface BriefFact {
  field: string;
  text: string;
  origin: "user" | "website";
  url: string;
}

export interface BriefConcept {
  title: string;
  visual: string;
  scenes: string[];
}

/** The validated plan the AI video was made from (backend/app/schemas.py AdBrief). */
export interface AdBrief {
  business_name: string;
  product_focus: string;
  audience: string;
  objective: string;
  main_message: string;
  hook: string;
  cta: string;
  supporting_facts: BriefFact[];
  concepts: BriefConcept[];
  chosen_concept: number;
  overlay_text: string[];
  brand_assets: string[];
  duration_seconds: number;
  aspect_ratio: string;
  missing: string[];
  rejected_claims: string[];
  builder: "llm" | "template";
}

export interface CompositionSegment {
  kind: SegmentKind;
  source: string;
  seconds: number;
}

export interface AdResponse {
  ad_id: string;
  job_id: string | null;
  status: AdStatus;
  stage: AdStage;
  progress: number;
  message: string;
  prompt: AdPrompt | null;
  video_url: string | null;
  provider: string;
  fallback_used: boolean;
  actual_duration_seconds: number | null;
  warnings: string[];
  error: string | null;
  options: AdOptions;
  creative: CreativeConfig | null;
  ai_video_used: boolean;
  qr_added: boolean;
  composition: CompositionSegment[];
  brief: AdBrief | null;
  provider_error: string | null;
  site_summary: string;
  overlay_text: string[];
  created_at: string;
  updated_at: string;
}

export interface CreativeModeInfo {
  id: "manual" | CreativeMode;
  creation_mode: CreationMode;
  label: string;
  description: string;
  uses_scraper: boolean;
  uses_prompt_writer: boolean;
  uses_ai_video: boolean;
  available: boolean;
  unavailable_reason: string;
}

export interface ConfigOption {
  id: string;
  label: string;
  aspect_ratio?: string;
  audience?: string;
  hint?: string;
  note?: string;
}

export interface ConfigResponse {
  api_version: string;
  demo_mode: boolean;
  video_provider: string;
  prompt_builder: "llm" | "template";
  max_video_seconds: number;
  durations: number[];
  platforms: ConfigOption[];
  goals: ConfigOption[];
  ad_types: ConfigOption[];
  voices: ConfigOption[];
  music: ConfigOption[];
  styles: ConfigOption[];
  tones: ConfigOption[];
  categories: ConfigOption[];
  max_upload_bytes: number;
  max_upload_files: number;
  phase2_mode: string;
  ai_video_available: boolean;
  ai_video_message: string;
  creative_modes: CreativeModeInfo[];
  compose_durations: number[];
  website_image_seconds: number;
  max_video_upload_bytes: number;
  max_video_upload_seconds: number;
}

export interface ErrorBody {
  detail: string;
  code: string;
}

export const FAILED_SCAN_STATUSES: JobStatus[] = [
  "blocked", "unreachable", "invalid_url", "unsupported_platform", "timeout", "internal_error",
];

// True when a scan ended in a state that gives no usable facts.
export function isScanFailure(status: JobStatus): boolean {
  return FAILED_SCAN_STATUSES.includes(status);
}

// True when an ad reached a final status.
export function isAdFinished(status: AdStatus): boolean {
  return status === "completed" || status === "completed_with_fallback" || status === "failed";
}
