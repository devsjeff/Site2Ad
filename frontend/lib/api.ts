// The ONE place the frontend talks to the backend. Every path below exists in backend/app/api/routes.py
// (checked by scripts/check_contract.py). The base URL comes from NEXT_PUBLIC_API_BASE_URL; empty means same origin.

import type {
  AdResponse, ConfigResponse, ErrorBody, GenerateAdRequest, JobResponse, UploadResponse,
} from "./types";

const RAW_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
// NEXT_PUBLIC_API_TARGET: "direct" (default) calls NEXT_PUBLIC_API_BASE_URL; "nginx" calls the page's own origin,
// where nginx forwards /api to the backend (deploy/nginx). Switch it in frontend/.env.local and restart / rebuild.
const API_TARGET = (process.env.NEXT_PUBLIC_API_TARGET ?? "direct").trim().toLowerCase();
export const API_BASE = API_TARGET === "nginx" ? "" : RAW_BASE.replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Full URL for an API path. Absolute URLs (already prefixed) are returned unchanged. */
export function apiUrl(path: string): string {
  return /^https?:\/\//i.test(path) ? path : `${API_BASE}${path}`;
}

// Turn a failed response into an ApiError with a readable message.
async function readError(response: Response): Promise<ApiError> {
  let body: Partial<ErrorBody> = {};
  try {
    body = (await response.json()) as Partial<ErrorBody>;
  } catch {
    // not JSON: fall through to the generic message
  }
  const message = typeof body.detail === "string" && body.detail ? body.detail : `Request failed (${response.status}).`;
  return new ApiError(response.status, body.code ?? "error", message);
}

// Fetch JSON from the API; network failures and error bodies become ApiError.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch {
    throw new ApiError(0, "network", "Cannot reach the server. Check your connection and that the backend is running.");
  }
  if (!response.ok) throw await readError(response);
  return (await response.json()) as T;
}

// POST a JSON body and read the JSON answer.
function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const api = {
  /** GET /api/config: options and limits of this server. */
  getConfig: () => request<ConfigResponse>("/api/config"),

  /** POST /api/scrape: start scanning a website. */
  startScrape: (url: string, refresh = false) => postJson<JobResponse>("/api/scrape", { url, refresh }),

  /** GET /api/jobs/{id}: progress and result of a scan. */
  getJob: (jobId: string) => request<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}`),

  /** POST /api/uploads: upload a logo, photos or videos. */
  upload(kind: "logo" | "photo" | "video", files: File[]): Promise<UploadResponse> {
    const form = new FormData();
    form.append("kind", kind);
    for (const file of files) form.append("files", file);
    return request<UploadResponse>("/api/uploads", { method: "POST", body: form });
  },

  /** POST /api/generate-ad: create ONE ad (one prompt, one video). */
  generateAd: (body: GenerateAdRequest) => postJson<AdResponse>("/api/generate-ad", body),

  /** GET /api/ads/{id}: progress, prompt and result of an ad. */
  getAd: (adId: string) => request<AdResponse>(`/api/ads/${encodeURIComponent(adId)}`),

  /** POST /api/ads/{id}/cancel: stop an ad that is still being made. */
  cancelAd: (adId: string) => postJson<AdResponse>(`/api/ads/${encodeURIComponent(adId)}/cancel`, {}),
};

/** URL of an uploaded image or video (for <img src> / <video src>). */
export function assetUrl(assetId: string): string {
  return apiUrl(`/api/assets/${encodeURIComponent(assetId)}`);
}

/** URL of the finished video (for <video src> or a download link). */
export function adVideoUrl(adId: string, download = false): string {
  return apiUrl(`/api/ads/${encodeURIComponent(adId)}/video${download ? "?download=1" : ""}`);
}

/** Human readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Please try again.";
}
