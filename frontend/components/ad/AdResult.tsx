"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { adVideoUrl, api, errorMessage } from "@/lib/api";
import { usePolling } from "@/lib/usePolling";
import { isAdFinished, type AdBrief, type AdResponse, type SegmentKind } from "@/lib/types";
import { Alert } from "../ui/Alert";
import { AdProgress } from "./AdProgress";
import { PromptView } from "./PromptView";

const AD_ID = /^[0-9a-f]{32}$/;

const SEGMENT_LABELS: Record<SegmentKind, string> = {
  website_image: "Original website image",
  uploaded_image: "Your photo",
  uploaded_video: "Your video",
  ai_video: "AI-generated video",
  fallback_video: "Simple clip made from your details (not AI footage)",
};

// The ad brief the AI video was planned from: concept, message, facts (with where they came from), what was left out.
function BriefView({ brief }: { brief: AdBrief }) {
  const concept = brief.concepts[brief.chosen_concept];
  return (
    <details className="rounded-xl border border-line bg-surface p-4 text-sm">
      <summary className="cursor-pointer font-medium text-ink">
        Ad brief
        <span className="ml-2 text-xs font-normal text-muted">{concept?.title} · written by {brief.builder === "llm" ? "AI" : "the built-in writer"}</span>
      </summary>
      <dl className="mt-3 space-y-2 text-xs">
        {brief.main_message && <div><dt className="font-medium text-ink">Message</dt><dd className="text-muted">{brief.main_message}</dd></div>}
        {concept && <div><dt className="font-medium text-ink">Scene</dt><dd className="text-muted">{concept.visual}</dd></div>}
        {brief.concepts.length > 1 && <div><dt className="font-medium text-ink">Other ideas</dt><dd className="text-muted">{brief.concepts.filter((_, i) => i !== brief.chosen_concept).map((c) => c.title).join(" · ")}</dd></div>}
        {brief.supporting_facts.length > 0 && (
          <div>
            <dt className="font-medium text-ink">Facts used</dt>
            <dd><ul className="list-disc pl-5 text-muted">{brief.supporting_facts.map((fact) => <li key={fact.field}>{fact.field}: {fact.text} <span className="opacity-70">({fact.origin === "user" ? "you typed it" : "from your website"})</span></li>)}</ul></dd>
          </div>
        )}
        {brief.rejected_claims.length > 0 && <div><dt className="font-medium text-ink">Left out</dt><dd><ul className="list-disc pl-5 text-muted">{brief.rejected_claims.map((c) => <li key={c}>{c}</li>)}</ul></dd></div>}
        {brief.missing.length > 0 && <div><dt className="font-medium text-ink">Not found (add it for a better ad)</dt><dd className="text-muted">{brief.missing.join(" · ")}</dd></div>}
      </dl>
    </details>
  );
}

// What the finished video is made of, in order, and whether the QR code really made it in.
function MadeOf({ ad }: { ad: AdResponse }) {
  if (ad.composition.length === 0) return null;
  const qr = ad.creative ? (ad.creative.include_qr ? (ad.qr_added ? `QR code added, opens ${ad.creative.qr_url}` : "QR code was requested but could not be added (see below)") : "No QR code") : null;
  return (
    <div className="rounded-xl border border-line bg-surface p-4 text-sm">
      <p className="font-medium text-ink">{ad.ai_video_used ? `Contains AI-generated footage (${ad.provider})` : "No AI-generated footage: built with FFmpeg from real images and video"}</p>
      <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-muted">
        {ad.composition.map((segment, index) => <li key={`${segment.kind}-${index}`}>{SEGMENT_LABELS[segment.kind]} · {segment.seconds.toFixed(1)} s</li>)}
      </ol>
      {qr && <p className="mt-2 text-xs text-muted">{qr}</p>}
    </div>
  );
}

// Polls one ad and shows progress, the finished video, warnings and the prompt.
export function AdResult() {
  const params = useParams<{ adId: string }>();
  const adId = typeof params?.adId === "string" ? params.adId : "";
  const valid = AD_ID.test(adId);
  const [shape, setShape] = useState<number | null>(null); // width / height of the finished video, read from the file
  const { data: ad, error } = usePolling<AdResponse>({
    fetcher: () => api.getAd(adId),
    isDone: (value) => isAdFinished(value.status),
    enabled: valid,
    resetKey: adId,
    startMs: 1500,
    maxMs: 5000,
  });

  if (!valid) return <Alert tone="error" title="This link does not look right">Start again from the create page.</Alert>;
  if (error && !ad) return <Alert tone="error" title="We could not load this ad">{errorMessage(error)}</Alert>;
  if (!ad) return <p className="py-16 text-center text-sm text-muted" aria-live="polite">Loading your ad…</p>;

  const again = ad.job_id ? `/ads/create?job=${ad.job_id}` : ad.creative?.creation_mode === "manual" ? "/ads/create?mode=manual" : "/ads/create";
  const ratio = shape ?? (ad.prompt?.aspect_ratio === "9:16" ? 9 / 16 : ad.prompt?.aspect_ratio === "1:1" ? 1 : 16 / 9);
  const vertical = ratio < 0.8;
  const square = !vertical && ratio < 1.2;

  return (
    <div className="space-y-6 animate-fadeUp">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-ink">
          {ad.status === "failed" ? "We could not finish your ad" : isAdFinished(ad.status) ? "Your ad is ready" : "Creating your ad"}
        </h1>
        {ad.prompt && !isAdFinished(ad.status) && <p className="mt-1 text-sm text-muted">Your prompt is ready. The video is being created.</p>}
      </header>

      {!isAdFinished(ad.status) && <AdProgress ad={ad} />}
      {error ? <Alert tone="warn" title="Connection problem">{errorMessage(error)} Reload the page to keep watching.</Alert> : null}

      {ad.status === "failed" && <Alert tone="error" title="Something went wrong">{ad.error || "Please try again."}</Alert>}

      {ad.status === "completed_with_fallback" && (
        <Alert tone="warn" title="Not AI footage">The AI video provider could not finish, so the video part is a simple clip, not AI-generated video. You can try again.{ad.provider_error ? ` Reason: ${ad.provider_error}` : ""}</Alert>
      )}
      {ad.provider === "mock" && ad.status === "completed" && (
        <Alert tone="info" title="Demo mode">This server has no video model key, so the video is a simple zoom clip made from your image. Add VIDEO_MODEL_API_KEY on the server for real AI video.</Alert>
      )}

      {isAdFinished(ad.status) && ad.status !== "failed" && <MadeOf ad={ad} />}

      {ad.video_url && (
        <div className="space-y-3">
          <div className={`mx-auto overflow-hidden rounded-2xl border border-line bg-black ${vertical ? "max-w-xs" : square ? "max-w-md" : "w-full"}`}>
            <video key={ad.ad_id} src={adVideoUrl(ad.ad_id)} controls playsInline preload="metadata" className="h-auto w-full" onLoadedMetadata={(e) => e.currentTarget.videoHeight > 0 && setShape(e.currentTarget.videoWidth / e.currentTarget.videoHeight)} />
          </div>
          <div className="flex flex-wrap justify-center gap-3">
            <a href={adVideoUrl(ad.ad_id, true)} className="inline-flex items-center rounded-xl bg-accent px-6 py-3 text-sm font-semibold text-white hover:opacity-90">Download MP4</a>
            <Link href={again} className="inline-flex items-center rounded-xl border border-line bg-surface px-6 py-3 text-sm font-semibold text-ink hover:border-accent">Make another ad</Link>
          </div>
        </div>
      )}

      {ad.status === "failed" && (
        <div className="flex justify-center">
          <Link href={again} className="inline-flex items-center rounded-xl bg-accent px-6 py-3 text-sm font-semibold text-white hover:opacity-90">Try again</Link>
        </div>
      )}

      {ad.warnings.length > 0 && (
        <Alert tone="info" title="Good to know">
          <ul className="list-disc space-y-1 pl-5">
            {ad.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </Alert>
      )}

      {ad.brief && <BriefView brief={ad.brief} />}
      {ad.prompt && <PromptView prompt={ad.prompt} />}
    </div>
  );
}
