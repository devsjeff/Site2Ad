"use client";

import React from "react";
import type { ConfigOption } from "@/lib/types";
import type { BusinessDraft, DraftField } from "@/lib/draft";
import { InputField } from "../ui/InputField";
import { SelectField } from "../ui/SelectField";

interface FactsFormProps {
  draft: BusinessDraft;
  autoFilled: ReadonlySet<DraftField>;
  detectedCategory: string;
  categories: ConfigOption[];
  onChange: (field: DraftField, value: string) => void;
  nameError?: string;
}

const FOUND = "Found on your website. Edit or clear it if it is wrong.";

// Form for the business details; values found on the website are pre-filled and marked.
export function FactsForm({ draft, autoFilled, detectedCategory, categories, onChange, nameError }: FactsFormProps) {
  // Help text for a field: says when the value was filled in from the website.
  const help = (field: DraftField, fallback: string) => (autoFilled.has(field) ? FOUND : fallback);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <InputField label="Business name" required value={draft.name} onChange={(v) => onChange("name", v)} placeholder="e.g. Sharma Sweets" maxLength={120} error={nameError} helpText={help("name", "Shown on the video.")} autoComplete="organization" />
      </div>
      <SelectField
        label="Category"
        value={draft.category}
        onChange={(v) => onChange("category", v)}
        options={categories.map((c) => ({ value: c.id, label: c.label }))}
        placeholder={detectedCategory ? `Detected: ${detectedCategory}` : "Choose a category (optional)"}
      />
      <InputField label="Phone number" value={draft.phone} onChange={(v) => onChange("phone", v)} placeholder="+91 98765 43210" maxLength={40} inputMode="tel" autoComplete="tel" helpText={help("phone", "Shown on the video. Leave empty to show none.")} />
      <div className="sm:col-span-2">
        <InputField label="Address" value={draft.address} onChange={(v) => onChange("address", v)} placeholder="Street, city" maxLength={240} autoComplete="street-address" helpText={help("address", "Shown on the video. Leave empty to show none.")} />
      </div>
      <InputField label="Offer" value={draft.offer} onChange={(v) => onChange("offer", v)} placeholder="e.g. 20% off on gift boxes" maxLength={160} helpText={help("offer", "Only add an offer that is real.")} />
      <InputField label="Call to action" value={draft.cta} onChange={(v) => onChange("cta", v)} placeholder="e.g. Order now" maxLength={80} helpText={help("cta", "A few words at the end of the ad.")} />
      <div className="sm:col-span-2">
        <InputField label="About the business" multiline value={draft.description} onChange={(v) => onChange("description", v)} placeholder="One or two sentences about what you do." maxLength={800} helpText={help("description", "Helps the video match your business.")} />
      </div>
    </div>
  );
}
