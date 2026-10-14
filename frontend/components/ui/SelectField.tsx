"use client";

import React, { useId } from "react";

interface SelectFieldProps {
  label: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  helpText?: string;
  placeholder?: string;
}

// Labelled dropdown.
export function SelectField({ label, options, value, onChange, helpText, placeholder = "Select an option" }: SelectFieldProps) {
  const id = useId();
  return (
    <div className="w-full">
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink shadow-sm transition-all focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      {helpText && <p className="mt-1.5 text-xs text-muted">{helpText}</p>}
    </div>
  );
}
