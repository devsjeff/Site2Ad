"use client";

import React, { useId } from "react";

interface InputFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  helpText?: string;
  required?: boolean;
  error?: string;
  maxLength?: number;
  inputMode?: "text" | "tel" | "url" | "email";
  autoComplete?: string;
  disabled?: boolean;
}

const BASE =
  "w-full rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink shadow-sm transition-all placeholder:text-muted/70 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60";

// Labelled text input or textarea with help and error text.
export function InputField({
  label, value, onChange, placeholder, multiline = false, helpText, required = false, error, maxLength, inputMode, autoComplete, disabled,
}: InputFieldProps) {
  const id = useId();
  return (
    <div className="w-full">
      <label htmlFor={id} className="mb-1.5 flex items-center text-sm font-medium text-ink">
        {label}
        {required && <span className="ml-1 text-danger" aria-hidden="true">*</span>}
      </label>
      {multiline ? (
        <textarea id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} required={required} rows={3} maxLength={maxLength} disabled={disabled} className={`${BASE} resize-y`} />
      ) : (
        <input id={id} type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} required={required} maxLength={maxLength} inputMode={inputMode} autoComplete={autoComplete} disabled={disabled} className={BASE} />
      )}
      {error ? <p className="mt-1.5 text-xs text-danger">{error}</p> : helpText ? <p className="mt-1.5 text-xs text-muted">{helpText}</p> : null}
    </div>
  );
}
