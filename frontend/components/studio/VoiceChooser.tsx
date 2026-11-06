"use client";

import React from "react";
import { languageLabel, voiceAfterLanguage, voicesFor } from "@/lib/studio";
import type { ConfigResponse } from "@/lib/types";
import { OptionCard } from "../ui/OptionCard";
import { SelectField } from "../ui/SelectField";

interface VoiceChooserProps {
  config: ConfigResponse;
  language: string;
  voice: string; // a voice id, "auto" (the AI chooses) or "none"
  onChange: (next: { language: string; voice: string }) => void;
}

// Language of the voiceover and the voice that speaks it. Studio-quality (ElevenLabs) voices show up when the server has a key for them.
export function VoiceChooser({ config, language, voice, onChange }: VoiceChooserProps) {
  const speaking = voicesFor(config.voices, language);
  const free = speaking.filter((v) => v.engine !== "eleven");
  const studio = speaking.filter((v) => v.engine === "eleven");
  const languages = config.languages.length > 0 ? config.languages : [{ id: "en", label: "English" }];
  const pick = (next: string) => onChange({ language, voice: next });

  return (
    <div className="space-y-4">
      <SelectField label="Language of the voiceover" value={language} placeholder="Choose a language"
        options={languages.map((l) => ({ value: l.id, label: languageLabel(l) }))}
        onChange={(next) => onChange({ language: next || language, voice: voiceAfterLanguage(config.voices, next || language, voice) })}
        helpText={language === "en" ? "The words on screen come from your website; the voice says them." : "The words on screen stay as your website wrote them. The voice-over is translated, keeping every number."} />
      <div>
        <p className="mb-2 text-sm font-medium text-ink">Voice</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" role="group" aria-label="Voice">
          <OptionCard compact icon="✨" title="Let the AI choose" selected={voice === "auto"} onClick={() => pick("auto")} />
          <OptionCard compact icon="🔇" title="No voice" selected={voice === "none"} onClick={() => pick("none")} />
          {free.map((v) => (
            <OptionCard key={v.id} compact icon="🎙️" title={v.label} description={v.hint} selected={voice === v.id} onClick={() => pick(v.id)} />
          ))}
        </div>
        {studio.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-muted">Studio-quality voices</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" role="group" aria-label="Studio-quality voices">
              {studio.map((v) => (
                <OptionCard key={v.id} compact icon="🎧" title={v.label.replace(" (ElevenLabs)", "")} description={v.hint} badge="ElevenLabs" selected={voice === v.id} onClick={() => pick(v.id)} />
              ))}
            </div>
          </div>
        )}
        {!config.eleven_available && <p className="mt-2 text-xs text-muted">Studio-quality ElevenLabs voices appear here once an ElevenLabs key is set on the server.</p>}
      </div>
    </div>
  );
}
