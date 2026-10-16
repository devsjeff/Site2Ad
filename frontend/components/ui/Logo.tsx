import Link from "next/link";
import React from "react";

// The site2ad word mark: a gradient play tile and the name.
export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="group flex items-center gap-2">
      <span className="bg-brand animate-gradient flex h-8 w-8 items-center justify-center rounded-xl text-white shadow-glow transition-transform group-hover:rotate-6 group-hover:scale-105">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true"><path d="M3 1.8v10.4L12 7z" /></svg>
      </span>
      <span className="text-lg font-extrabold tracking-tight text-ink">site<span className="text-brand">2</span>ad</span>
    </Link>
  );
}
