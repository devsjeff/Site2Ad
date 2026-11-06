"use client";

import React, { useState } from "react";
import { studioShotUrl } from "@/lib/api";
import { languageLabel, splitLines, voiceAfterLanguage, voicesFor } from "@/lib/studio";
import type { ConfigResponse, StudioAssumptions, StudioResponse } from "@/lib/types";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { InputField } from "../ui/InputField";
import { SelectField } from "../ui/SelectField";
import { Toggle } from "../ui/Toggle";

interface StudioReviewProps {
  job: StudioResponse;
  config: ConfigResponse;
  busy: boolean;
  error: string | null;
  onContinue: (assumptions: StudioAssumptions) => void;
  onCancel: () => void;
}

function Swatch({ label, color }: { label: string; color: string }) {
  return (
    <li className="flex items-center gap-2 text-xs">
      <span className="h-7 w-7 rounded-full ring-2 ring-line" style={{ backgroundColor: color }} aria-hidden="true" />
      <span><span className="block font-semibold text-ink">{label}</span><span className="text-muted">{color}</span></span>
    </li>
  );
}

// The plan after the notes: what was found, with sources, and the choices the person can correct before the video is made.
export function StudioReview({ job, config, busy, error, onContinue, onCancel }: StudioReviewProps) {
  const start = job.assumptions;
  const [form, setForm] = useState<StudioAssumptions | null>(start);
  const [include, setInclude] = useState(() => (start?.must_include ?? []).map((item) => item.what).join("\n"));
  const [avoid, setAvoid] = useState(() => (start?.must_avoid ?? []).join("\n"));
  if (!form || !start) return <Alert tone="error">The plan is not ready yet. Reload the page in a moment.</Alert>;

  const set = <K extends keyof StudioAssumptions>(key: K, value: StudioAssumptions[K]) => setForm((current) => (current ? { ...current, [key]: value } : current));
  const voices = voicesFor(config.voices, form.language).map((v) => ({ value: v.id, label: v.hint ? `${v.label}: ${v.hint}` : v.label }));
  const languages = (config.languages.length > 0 ? config.languages : [{ id: "en", label: "English" }]).map((l) => ({ value: l.id, label: languageLabel(l) }));
  const tracks = config.music.filter((m) => m.id !== "auto").map((m) => ({ value: m.id, label: m.label }));

  // Wishes keep their cited claims when the text is unchanged; lines that were added cite nothing (the writer still has to find a source).
  function submit() {
    if (!form) return;
    const known = new Map(start!.must_include.map((item) => [item.what.toLowerCase(), item.claims]));
    const wishes = splitLines(include, 6).map((what) => ({ what, claims: known.get(what.toLowerCase()) ?? [] }));
    onContinue({ ...form, must_include: wishes, must_avoid: splitLines(avoid, 6) });
  }

  const brand = job.brand;
  const canSend = form.audience.trim() && form.key_message.trim() && form.cta_text.trim();

  return (
    <section className="space-y-6 animate-fadeUp">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-ink">Check the <span className="text-brand">plan</span></h1>
        <p className="mt-1.5 text-sm text-muted">This is what we understood from {job.url}. Fix anything that is wrong, then we make the video.</p>
      </div>

      <div className="space-y-3 rounded-3xl border border-line bg-surface/85 p-5">
        <h2 className="text-sm font-bold text-ink">What we found</h2>
        <p className="text-sm text-ink">{job.what_it_is}</p>
        {job.who_for && <p className="text-sm text-muted"><span className="font-semibold text-ink">For: </span>{job.who_for}</p>}
        {job.claims.length > 0 && (
          <ul className="space-y-1.5" aria-label="Claims we may use">
            {job.claims.map((claim) => (
              <li key={claim.id} className="flex flex-wrap items-baseline gap-2 text-sm">
                <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-bold text-ink">{claim.id}</span>
                <span className="text-ink">{claim.text}</span>
                <span className="text-xs text-muted">({claim.source})</span>
              </li>
            ))}
          </ul>
        )}
        {job.claims.length === 0 && <Alert tone="warn">No facts with a source were found. The video will stay general. Go back and add your own facts for a stronger one.</Alert>}
      </div>

      {job.screenshots.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-bold text-ink">Pictures taken from the site</h2>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {job.screenshots.map((shot) => (
              <li key={shot.id} className="overflow-hidden rounded-xl border border-line bg-surface/80">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={studioShotUrl(job.job_id, shot.file)} alt={shot.summary || `Screenshot ${shot.id}`} loading="lazy" className="aspect-video w-full object-cover object-top" />
                <p className="truncate px-2 py-1 text-[11px] text-muted" title={shot.summary}>{shot.id} · {shot.kind}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {brand && (
        <div className="space-y-3 rounded-3xl border border-line bg-surface/85 p-5">
          <h2 className="text-sm font-bold text-ink">Brand look</h2>
          <ul className="flex flex-wrap gap-4">
            <Swatch label="Main" color={brand.primary} />
            <Swatch label="Accent" color={brand.accent} />
            <Swatch label="Background" color={brand.background} />
            <Swatch label="Text" color={brand.ink} />
          </ul>
          <p className="text-xs text-muted">Fonts: {brand.heading_font} / {brand.body_font} · Shapes: {brand.shapes} · Tone: {brand.tone}</p>
        </div>
      )}

      <div className="space-y-5 rounded-3xl border border-line bg-surface/85 p-5 shadow-glow">
        <h2 className="text-sm font-bold text-ink">Our choices (change what you like)</h2>
        <InputField label="Who is it for?" value={form.audience} onChange={(v) => set("audience", v)} maxLength={200} />
        <InputField label="The one message" value={form.key_message} onChange={(v) => set("key_message", v)} maxLength={160} helpText="One idea, said once." />
        <InputField label="Tone" value={form.tone} onChange={(v) => set("tone", v)} maxLength={120} />
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField label="Language of the voice-over" value={form.language} placeholder="Choose a language" options={languages}
            onChange={(v) => setForm((current) => (current ? { ...current, language: v || current.language, voice: voiceAfterLanguage(config.voices, v || current.language, current.voice, false) } : current))}
            helpText={form.language === "en" ? "" : "Translated by the AI writer with every figure kept; the words on screen stay as your website wrote them."} />
          <SelectField label="Voice" value={form.voice} onChange={(v) => set("voice", v)} placeholder="Choose a voice" helpText={form.voice_reason}
            options={[...voices, { value: "none", label: "No voice" }]} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField label="Music" value={form.music} onChange={(v) => set("music", v)} placeholder="Choose music" helpText={form.music_reason} options={tracks} />
        </div>
        <Toggle checked={form.sound_effects} onChange={(v) => set("sound_effects", v)} title="Sound effects" help="Whooshes, pops and a chime that follow the animation." />
        <div className="grid gap-4 sm:grid-cols-2">
          <InputField label="Call to action" value={form.cta_text} onChange={(v) => set("cta_text", v)} maxLength={40} helpText="The one thing to do, at most four words." />
          <InputField label="Where it goes" value={form.cta_target} onChange={(v) => set("cta_target", v)} maxLength={80} />
        </div>
        <InputField label="Must include (one per line)" multiline value={include} onChange={setInclude} maxLength={600} />
        <InputField label="Must avoid (one per line)" multiline value={avoid} onChange={setAvoid} maxLength={600} />
      </div>

      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
        <Button onClick={submit} loading={busy} disabled={!canSend} className="py-4 text-base">🎬 Save and make my video</Button>
      </div>
    </section>
  );
}
