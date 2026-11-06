"use client";

import React from "react";
import { studioShotUrl, studioVideoUrl } from "@/lib/api";
import { playerShape, seconds, TYPE_ICONS } from "@/lib/studio";
import type { StudioResponse } from "@/lib/types";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";

interface StudioResultProps {
  job: StudioResponse;
  onAgain: () => void;
}

// A finished video with its download, the shots with the claims behind them, and the result of the final check.
export function StudioResult({ job, onAgain }: StudioResultProps) {
  const total = job.shots.reduce((sum, shot) => sum + shot.seconds, 0);
  return (
    <section className="space-y-6 animate-fadeUp">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-ink">Your <span className="text-brand">video</span> is ready {TYPE_ICONS[job.video_type]}</h1>
        <p className="mt-1.5 truncate text-sm text-muted">{job.url} · {job.length} s · {job.platform}</p>
      </div>

      <div className="overflow-hidden rounded-3xl border border-line bg-black shadow-glow">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video src={studioVideoUrl(job.job_id)} controls playsInline preload="metadata" className={`${playerShape(job.platform)} bg-black`} />
      </div>
      <div className="flex flex-wrap gap-3">
        <a href={studioVideoUrl(job.job_id, true)} download className="bg-brand animate-gradient shine shadow-glow inline-flex items-center justify-center rounded-2xl px-6 py-3 text-sm font-bold text-white transition-transform hover:-translate-y-0.5 active:scale-[0.98]">
          ⬇ Download
        </a>
        <Button variant="secondary" onClick={onAgain}>Make another</Button>
      </div>

      {job.passed === true && job.problems.length === 0 && <Alert tone="success" title="Checked">Every number, price and claim in the video matches your website notes.</Alert>}
      {(job.passed === false || job.problems.length > 0) && (
        <Alert tone="warn" title="Please look at these before you use it">
          <ul className="list-disc pl-5">{job.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </Alert>
      )}

      <div className="space-y-3">
        <h2 className="text-sm font-bold text-ink">The shots ({job.shots.length}, {seconds(total)})</h2>
        <ol className="space-y-3">
          {job.shots.map((shot) => (
            <li key={shot.n} className="flex gap-3 rounded-2xl border border-line bg-surface/85 p-3">
              {shot.screenshot ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={studioShotUrl(job.job_id, shot.screenshot)} alt="" loading="lazy" className="h-16 w-24 shrink-0 rounded-lg object-cover object-top" />
              ) : (
                <span className="flex h-16 w-24 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-xl font-extrabold text-ink" aria-hidden="true">{shot.n}</span>
              )}
              <div className="min-w-0 flex-1 text-sm">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-ink">{shot.n}. {shot.purpose}</span>
                  <span className="text-xs text-muted">{seconds(shot.seconds)} · {shot.transition}</span>
                </p>
                {shot.voice && <p className="mt-0.5 text-ink">“{shot.voice}”</p>}
                {shot.voice_local && <p className="text-sm font-medium text-accent"><span aria-hidden="true">🗣 </span>{shot.voice_local}</p>}
                {shot.caption && shot.caption !== shot.voice && <p className="text-xs font-semibold text-accent">On screen: {shot.caption}</p>}
                {shot.claims.length > 0 && (
                  <p className="mt-1 flex flex-wrap gap-1" aria-label="Claims used">
                    {shot.claims.map((id) => <span key={id} className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-bold text-ink">{id}</span>)}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
