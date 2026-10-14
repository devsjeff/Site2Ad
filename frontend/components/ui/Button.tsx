"use client";

import React from "react";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

const STYLES: Record<Variant, string> = {
  primary: "bg-accent text-white hover:opacity-90 disabled:opacity-50",
  secondary: "border border-line bg-surface text-ink hover:border-accent disabled:opacity-50",
  ghost: "text-muted hover:text-ink disabled:opacity-50",
};

// Primary / secondary button with a loading state.
export function Button({ variant = "primary", loading = false, disabled, children, className = "", type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold transition-all active:scale-[0.98] disabled:cursor-not-allowed ${STYLES[variant]} ${className}`}
      {...rest}
    >
      {loading && <Spinner size={16} />}
      {children}
    </button>
  );
}
