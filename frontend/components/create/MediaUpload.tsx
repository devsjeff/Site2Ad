"use client";

import React, { useRef, useState } from "react";
import { api, assetUrl, errorMessage } from "@/lib/api";
import type { AssetInfo } from "@/lib/types";
import { Spinner } from "../ui/Spinner";

interface MediaUploadProps {
  assets: AssetInfo[];
  maxFiles: number;
  maxVideoMb: number;
  maxVideoSeconds: number;
  onChange: (assets: AssetInfo[]) => void;
  onError: (message: string | null) => void;
}

const IMAGE_TYPES = "image/png,image/jpeg,image/webp";
const VIDEO_TYPES = "video/mp4,video/quicktime,video/webm";

// Upload box for a manual ad: photos and videos together, kept in the order they will play. The server checks every file.
export function MediaUpload({ assets, maxFiles, maxVideoMb, maxVideoSeconds, onChange, onError }: MediaUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const room = Math.max(0, maxFiles - assets.length);

  // Upload images as photos and videos as videos (one request per file keeps the play order).
  async function send(files: File[]) {
    const chosen = files.filter((file) => file.type.startsWith("image/") || file.type.startsWith("video/")).slice(0, room);
    if (chosen.length === 0) {
      onError(files.length > 0 ? "Choose JPG, PNG or WebP images, or MP4, MOV or WebM videos." : null);
      return;
    }
    setBusy(true);
    onError(null);
    let current = assets;
    try {
      for (const file of chosen) {
        const done = await api.upload(file.type.startsWith("video/") ? "video" : "photo", [file]);
        current = [...current, ...done.assets];
        onChange(current);
      }
    } catch (error) {
      onError(errorMessage(error));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  // Move one upload earlier or later in the play order.
  function move(index: number, step: -1 | 1) {
    const next = [...assets];
    const target = index + step;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <div className="w-full">
      <p className="mb-1.5 text-sm font-medium text-ink">Your images and videos</p>
      <div
        role="button"
        tabIndex={0}
        aria-label="Your images and videos: click or drop files"
        onClick={() => room > 0 && !busy && inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && room > 0 && !busy && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); void send(Array.from(e.dataTransfer.files)); }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
          dragging ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-accent/60"
        } ${room === 0 ? "cursor-not-allowed opacity-60" : ""}`}
      >
        <input ref={inputRef} type="file" accept={`${IMAGE_TYPES},${VIDEO_TYPES}`} multiple className="hidden" onChange={(e) => void send(Array.from(e.target.files ?? []))} />
        {busy ? <Spinner /> : <span className="text-2xl" aria-hidden="true">🎞️</span>}
        <p className="mt-1 text-sm font-medium text-ink">{busy ? "Uploading and checking…" : room > 0 ? "Click to upload or drop here" : "Limit reached"}</p>
        <p className="text-xs text-muted">Photos (JPG, PNG, WebP) or videos (MP4, MOV, WebM up to {maxVideoMb} MB and {maxVideoSeconds} seconds). They play in this order.</p>
      </div>
      {assets.length > 0 && (
        <ol className="mt-3 space-y-2">
          {assets.map((asset, index) => (
            <li key={asset.asset_id} className="flex items-center gap-3 rounded-lg border border-line bg-surface p-2">
              <span className="w-5 text-center text-xs font-semibold text-muted">{index + 1}</span>
              <div className="h-12 w-16 shrink-0 overflow-hidden rounded-md border border-line bg-black">
                {asset.media_type === "video" ? (
                  <video src={assetUrl(asset.asset_id)} muted playsInline preload="metadata" className="h-full w-full object-cover" />
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={assetUrl(asset.asset_id)} alt={asset.filename || "Uploaded image"} className="h-full w-full object-cover" />
                )}
              </div>
              <div className="min-w-0 flex-1 text-xs">
                <p className="truncate font-medium text-ink">{asset.filename || (asset.media_type === "video" ? "Video" : "Photo")}</p>
                <p className="text-muted">
                  {asset.media_type === "video"
                    ? `Video · ${asset.duration_seconds.toFixed(1)} s · ${asset.has_audio ? "with sound" : "no sound"}`
                    : `Photo · ${asset.width}×${asset.height}`}
                </p>
              </div>
              <div className="flex gap-1">
                <button type="button" aria-label="Play earlier" disabled={index === 0} onClick={() => move(index, -1)} className="rounded px-2 py-1 text-xs text-muted hover:text-ink disabled:opacity-30">↑</button>
                <button type="button" aria-label="Play later" disabled={index === assets.length - 1} onClick={() => move(index, 1)} className="rounded px-2 py-1 text-xs text-muted hover:text-ink disabled:opacity-30">↓</button>
                <button type="button" aria-label={`Remove ${asset.filename || "file"}`} onClick={() => onChange(assets.filter((a) => a.asset_id !== asset.asset_id))} className="rounded px-2 py-1 text-xs text-muted hover:text-danger">×</button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
