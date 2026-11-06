"use client";

import React, { useState } from "react";
import { fitLength, lengthChoices, PLATFORM_CHOICES, splitLines, TYPE_ICONS } from "@/lib/studio";
import type { ConfigResponse, StudioPlatform, StudioRequest, StudioVideoType } from "@/lib/types";
import { Advanced } from "../ui/Advanced";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { InputField } from "../ui/InputField";
import { OptionCard } from "../ui/OptionCard";
import { Toggle } from "../ui/Toggle";
import { VoiceChooser } from "./VoiceChooser";

interface StudioFormProps {
  config: ConfigResponse;
  busy: boolean;
  error: string | null;
  onStart: (request: StudioRequest) => void;
  /** The website is already known (the Make-an-ad flow asked for it earlier): shown instead of the address box. */
  url?: string;
  onBack?: () => void;
}

// The start screen: the website, the kind of video, its length and its shape.
export function StudioForm({ config, busy, error, onStart, url: knownUrl, onBack }: StudioFormProps) {
  const types = config.studio_types;
  const [typedUrl, setTypedUrl] = useState("");
  const url = knownUrl || typedUrl;
  const [videoType, setVideoType] = useState<StudioVideoType>("promo");
  const [length, setLength] = useState(20);
  const [platform, setPlatform] = useState<StudioPlatform>("16:9");
  const [facts, setFacts] = useState("");
  const [review, setReview] = useState(true);
  const [language, setLanguage] = useState("en");
  const [voice, setVoice] = useState("auto");
  const [soundEffects, setSoundEffects] = useState(true);

  const current = types.find((t) => t.id === videoType) ?? types[0];
  const minLength = current?.min_length ?? 10;
  const choices = lengthChoices(minLength);
  const chosenFacts = splitLines(facts);

  function pick(type: StudioVideoType) {
    setVideoType(type);
    const info = types.find((t) => t.id === type);
    if (info) setLength((value) => fitLength(value, info.min_length));
  }

  return (
    <section className="space-y-7 animate-fadeUp">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-ink">{knownUrl ? <>Design your <span className="text-brand">Studio video</span></> : <>Make a <span className="text-brand">studio video</span></>}</h1>
        <p className="mt-1.5 text-sm text-muted">A video built from what your website really says: every number and claim has a source, and you can correct the plan before it is made.</p>
      </div>

      {!config.studio_available && <Alert tone="warn" title="Studio is not set up on this server">{config.studio_message}</Alert>}

      {knownUrl ? (
        <p className="flex items-center gap-2 rounded-2xl border border-line bg-surface/85 px-4 py-3 text-sm text-ink">
          <span aria-hidden="true">🔗</span><span className="min-w-0 truncate"><span className="text-muted">Built from </span><b>{knownUrl}</b></span>
        </p>
      ) : (
        <div className="rounded-3xl border border-line bg-surface/85 p-5 shadow-glow">
          <InputField label="Website address" value={typedUrl} onChange={setTypedUrl} placeholder="yourbusiness.com" inputMode="url" autoComplete="url" />
        </div>
      )}

      <div className="space-y-3">
        <h3 className="text-sm font-bold text-ink">What kind of video?</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {types.map((type) => (
            <OptionCard key={type.id} compact icon={TYPE_ICONS[type.id]} title={type.label} selected={videoType === type.id} onClick={() => pick(type.id)} />
          ))}
        </div>
        {current && (
          <div className="animate-expand rounded-2xl border border-accent/25 bg-accent-soft/50 p-4" aria-live="polite">
            <p className="text-sm text-ink">{current.description}</p>
            <ol className="mt-3 flex flex-wrap items-center gap-1.5 text-xs font-semibold" aria-label={`The ${current.label} shots`}>
              {current.shots.map((shot, index) => (
                <li key={`${shot}-${index}`} className="flex items-center gap-1.5">
                  <span className="rounded-full bg-surface px-3 py-1 text-ink ring-1 ring-line">{shot}</span>
                  {index < current.shots.length - 1 && <span className="text-muted" aria-hidden="true">→</span>}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>

      <div className="grid gap-7 sm:grid-cols-2">
        <section>
          <h3 className="mb-3 text-sm font-bold text-ink">Length</h3>
          <div className="inline-flex flex-wrap gap-1 rounded-2xl border border-line bg-surface/80 p-1" role="group" aria-label="Video length">
            {choices.map((seconds) => (
              <button key={seconds} type="button" aria-pressed={length === seconds} onClick={() => setLength(seconds)}
                className={`rounded-xl px-4 py-2 text-sm font-bold transition-all duration-200 ${length === seconds ? "bg-brand animate-gradient text-white shadow-glow" : "text-muted hover:bg-accent-soft hover:text-ink"}`}>
                {seconds}s
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">{current ? `${current.label} has ${current.shots.length} shots; each needs about two seconds to be read.` : ""}</p>
        </section>
        <section>
          <h3 className="mb-3 text-sm font-bold text-ink">Shape</h3>
          <div className="grid grid-cols-3 gap-2" role="group" aria-label="Video shape">
            {PLATFORM_CHOICES.map((choice) => (
              <button key={choice.id} type="button" aria-pressed={platform === choice.id} onClick={() => setPlatform(choice.id)}
                className={`flex flex-col items-center gap-1.5 rounded-2xl border-2 p-3 text-center transition-all duration-200 hover:-translate-y-0.5 ${platform === choice.id ? "ring-brand shadow-glow" : "border-line bg-surface/85 hover:border-accent/50"}`}>
                <span className="rounded-md bg-accent-soft ring-2 ring-accent/40" style={{ width: choice.w, height: choice.h }} aria-hidden="true" />
                <span className="text-xs font-bold text-ink">{choice.label}</span>
                <span className="text-[10px] leading-tight text-muted">{choice.hint}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="space-y-4 rounded-3xl border border-line bg-surface/85 p-5">
        <h3 className="text-sm font-bold text-ink">Voice and sound</h3>
        <VoiceChooser config={config} language={language} voice={voice} onChange={(next) => { setLanguage(next.language); setVoice(next.voice); }} />
        <Toggle checked={soundEffects} onChange={setSoundEffects} title="Sound effects" help="Whooshes, pops and a chime that follow the animation, so the video feels alive even without a voice." />
      </section>

      <Advanced hint="Your own facts, and whether to stop for your review">
        <InputField label="Facts of your own (optional)" multiline value={facts} onChange={setFacts} maxLength={1200}
          placeholder={"Priya, a customer: “It doubled our walk-ins.”\nFree demo every Friday"}
          helpText={`One per line, up to 5 (${chosenFacts.length} added). They are used as if they were on your website, for example a real customer quote or a price. Only add what is true.`} />
        <Toggle checked={review} onChange={setReview} title="Let me correct the plan before the video is made"
          help="We stop after the notes and show you the audience, message, voice and music we chose. Recommended." />
      </Advanced>

      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex items-center justify-between">
        {onBack ? <Button variant="ghost" onClick={onBack} disabled={busy}>← Back</Button> : <span />}
        <Button onClick={() => onStart({ url: url.trim(), video_type: videoType, length, platform, claims: chosenFacts, review, language, voice, sound_effects: soundEffects })} loading={busy}
          disabled={!url.trim() || !config.studio_available} className="min-w-52 py-4 text-base">
          🎬 Make my video
        </Button>
      </div>
    </section>
  );
}
