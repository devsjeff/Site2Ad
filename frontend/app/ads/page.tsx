import Link from "next/link";

export const metadata = { title: "Ads | Adsify" };

const ENTRIES = [
  { href: "/ads/create?mode=auto", icon: "✨", title: "Auto ad", text: "Start from your website: original website content, an AI-generated video, or a mix of both." },
  { href: "/ads/create?mode=manual", icon: "🎬", title: "Manual ad", text: "Upload your own images or videos and add a QR code, text and your logo. No AI video." },
];

// Ads dashboard: the entry point for creating an ad.
export default function AdsPage() {
  return (
    <div className="space-y-8 animate-fadeUp">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">Ads</h1>
          <p className="mt-1 text-sm text-muted">Create a short video ad for taxi screens, Reels, Shorts or your feed.</p>
        </div>
        <Link href="/ads/create" className="inline-flex items-center justify-center rounded-xl bg-accent px-6 py-3 text-sm font-semibold text-white transition-all hover:opacity-90 active:scale-[0.98]">
          Create ad
        </Link>
      </header>
      <ul className="grid gap-3 sm:grid-cols-2">
        {ENTRIES.map((entry) => (
          <li key={entry.href}>
            <Link href={entry.href} className="flex h-full flex-col rounded-xl border-2 border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-accent/60 hover:shadow-md">
              <span className="mb-2 text-2xl" aria-hidden="true">{entry.icon}</span>
              <span className="text-sm font-semibold text-ink">{entry.title}</span>
              <span className="mt-1 text-xs leading-relaxed text-muted">{entry.text}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
