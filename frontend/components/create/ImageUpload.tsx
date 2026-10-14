"use client";

import React, { useRef, useState } from "react";
import { api, assetUrl, errorMessage } from "@/lib/api";
import type { AssetInfo } from "@/lib/types";
import { Spinner } from "../ui/Spinner";

interface ImageUploadProps {
  kind: "logo" | "photo";
  label: string;
  hint: string;
  assets: AssetInfo[];
  maxFiles: number;
  onChange: (assets: AssetInfo[]) => void;
  onError: (message: string | null) => void;
}

// Upload box for a logo or photos, with previews.
export function ImageUpload({ kind, label, hint, assets, maxFiles, onChange, onError }: ImageUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const room = Math.max(0, maxFiles - assets.length);

  // Upload the chosen files and report the new assets.
  async function send(files: File[]) {
    const chosen = files.filter((file) => file.type.startsWith("image/")).slice(0, room);
    if (chosen.length === 0) {
      onError(files.length > 0 ? "Please choose JPG, PNG or WebP images." : null);
      return;
    }
    setBusy(true);
    onError(null);
    try {
      const done = await api.upload(kind, chosen);
      onChange(kind === "logo" ? done.assets.slice(0, 1) : [...assets, ...done.assets]);
    } catch (error) {
      onError(errorMessage(error));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="w-full">
      <p className="mb-1.5 text-sm font-medium text-ink">{label}</p>
      <div
        role="button"
        tabIndex={0}
        aria-label={`${label}: click or drop images`}
        onClick={() => room > 0 && inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && room > 0 && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); void send(Array.from(e.dataTransfer.files)); }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-5 text-center transition-colors ${
          dragging ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-accent/60"
        } ${room === 0 ? "cursor-not-allowed opacity-60" : ""}`}
      >
        <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple={kind === "photo"} className="hidden" onChange={(e) => void send(Array.from(e.target.files ?? []))} />
        {busy ? <Spinner /> : <span className="text-2xl" aria-hidden="true">{kind === "logo" ? "🏷️" : "🖼️"}</span>}
        <p className="mt-1 text-sm font-medium text-ink">{busy ? "Uploading…" : room > 0 ? "Click to upload or drop here" : "Limit reached"}</p>
        <p className="text-xs text-muted">{hint}</p>
      </div>
      {assets.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {assets.map((asset) => (
            <li key={asset.asset_id} className="relative h-16 w-16 overflow-hidden rounded-lg border border-line bg-surface">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={assetUrl(asset.asset_id)} alt={asset.filename || "Uploaded image"} className="h-full w-full object-cover" />
              <button type="button" aria-label={`Remove ${asset.filename || "image"}`} onClick={() => onChange(assets.filter((a) => a.asset_id !== asset.asset_id))} className="absolute right-0.5 top-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-black/70 text-xs text-white hover:bg-black">×</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
