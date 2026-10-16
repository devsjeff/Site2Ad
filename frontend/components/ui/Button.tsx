"use client";

import React from "react";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

const STYLES: Record<Variant, string> = {
  primary: "bg-brand animate-gradient shine shadow-glow text-white hover:-translate-y-0.5 hover:brightness-110 disabled:opacity-50 disabled:hover:translate-y-0",
  secondary: "border border-line bg-surface/80 text-ink hover:-translate-y-0.5 hover:border-accent hover:text-accent disabled:opacity-50",
  ghost: "text-muted hover:bg-accent-soft/60 hover:text-ink disabled:opacity-50",
};

// Primary / secondary button with a loading state.
export function Button({ variant = "primary", loading = false, disabled, children, className = "", type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-2xl px-6 py-3 text-sm font-bold transition-all duration-200 active:scale-[0.97] disabled:cursor-not-allowed ${STYLES[variant]} ${className}`}
      {...rest}
    >
      {loading && <Spinner size={16} />}
      {children}
    </button>
  );
}
