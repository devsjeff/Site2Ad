import Link from "next/link";

export const metadata = { title: "Ads | site2ad" };

const ENTRIES = [
  { href: "/ads/create?mode=auto", icon: "✨", title: "Auto ad", text: "Start from your website: original website content, an AI-generated video, or a mix of both.", tint: "from-violet-500/25 via-fuchsia-500/10 to-transparent" },
  { href: "/ads/create?mode=manual", icon: "🎬", title: "Manual ad", text: "Upload your own images or videos and add a QR code, text and your logo. No AI video.", tint: "from-amber-400/25 via-pink-500/10 to-transparent" },
];

// Ads dashboard: the entry point for creating an ad.
export default function AdsPage() {
  return (
    <div className="space-y-8 animate-fadeUp">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-ink">Your <span className="text-brand">ads</span></h1>
          <p className="mt-1 text-sm text-muted">Create a short video ad for taxi screens, Reels, Shorts or your feed.</p>
        </div>
        <Link href="/ads/create" className="bg-brand animate-gradient shine shadow-glow inline-flex items-center justify-center rounded-2xl px-6 py-3 text-sm font-bold text-white transition-transform hover:-translate-y-0.5 active:scale-[0.98]">
          + Create ad
        </Link>
      </header>
      <ul className="grid gap-4 sm:grid-cols-2">
        {ENTRIES.map((entry, index) => (
          <li key={entry.href} className={`animate-fadeUp delay-${index + 1}`}>
            <Link href={entry.href} className="group relative flex h-full flex-col overflow-hidden rounded-3xl border border-line bg-surface/85 p-6 transition-all hover:-translate-y-1 hover:shadow-glow">
              <div className={`absolute inset-0 bg-gradient-to-br ${entry.tint} opacity-60 transition-opacity group-hover:opacity-100`} aria-hidden="true" />
              <span className="relative mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface text-2xl shadow-sm transition-transform group-hover:scale-110 group-hover:-rotate-6" aria-hidden="true">{entry.icon}</span>
              <span className="relative text-base font-bold text-ink">{entry.title}</span>
              <span className="relative mt-1 text-sm leading-relaxed text-muted">{entry.text}</span>
              <span className="relative mt-4 text-sm font-semibold text-accent transition-transform group-hover:translate-x-1">Start →</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
