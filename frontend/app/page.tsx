import Link from "next/link";
import { Logo } from "@/components/ui/Logo";

const STEPS = [
  { num: "1", icon: "🔗", title: "Paste your website", sub: "We read it and pull out your business name, offer and best photos.", tint: "from-violet-500/20 to-fuchsia-500/10" },
  { num: "2", icon: "🎨", title: "Pick a look", sub: "Website photos, AI video or a mix, for a taxi screen, Reel or Short.", tint: "from-pink-500/20 to-orange-400/10" },
  { num: "3", icon: "🎬", title: "Get your video ad", sub: "Ready in minutes, with your details added as clean, animated text.", tint: "from-amber-400/20 to-cyan-400/10" },
];

const CHIPS = ["🚕 Taxi screens", "📸 Instagram Reels", "▶️ YouTube Shorts", "👍 Facebook feed"];

// Landing page: headline, call to action and the three steps.
export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <nav className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5">
        <Logo />
        <Link href="/ads" className="rounded-full border border-line bg-surface/70 px-4 py-2 text-sm font-semibold text-ink transition-all hover:border-accent hover:text-accent">
          My ads →
        </Link>
      </nav>

      <main className="flex flex-1 flex-col items-center justify-center px-6 pb-20">
        <div className="w-full max-w-2xl space-y-8 text-center">
          <div className="space-y-5">
            <p className="animate-fadeUp mx-auto inline-flex items-center gap-2 rounded-full border border-line bg-surface/70 px-4 py-1.5 text-xs font-semibold text-muted">
              <span className="h-2 w-2 animate-pulse rounded-full bg-pink" /> Website → video ad in minutes
            </p>
            <h1 className="animate-fadeUp delay-1 text-4xl font-extrabold leading-tight tracking-tight text-ink sm:text-6xl">
              Turn your website into a <span className="text-brand">scroll-stopping</span> video ad
            </h1>
            <p className="animate-fadeUp delay-2 mx-auto max-w-lg text-lg leading-relaxed text-muted">
              Paste your link, pick a look, and get a short professional video. No design skills needed.
            </p>
          </div>
          <div className="animate-fadeUp delay-3 flex flex-col items-center justify-center gap-3 pt-2 sm:flex-row">
            <Link href="/ads/create?mode=auto" className="bg-brand animate-gradient shine shadow-glow w-full rounded-2xl px-8 py-4 text-base font-bold text-white transition-transform hover:-translate-y-0.5 active:scale-[0.98] sm:w-auto">
              ✨ Create my ad
            </Link>
            <Link href="/ads/create?mode=manual" className="w-full rounded-2xl border border-line bg-surface/80 px-8 py-4 text-base font-semibold text-ink transition-all hover:-translate-y-0.5 hover:border-accent sm:w-auto">
              Use my own photos
            </Link>
          </div>
          <ul className="animate-fadeUp delay-4 flex flex-wrap justify-center gap-2 pt-2">
            {CHIPS.map((chip) => (
              <li key={chip} className="rounded-full bg-surface/70 px-3 py-1 text-xs font-medium text-muted ring-1 ring-line">{chip}</li>
            ))}
          </ul>
        </div>

        <ol className="mt-20 grid w-full max-w-4xl grid-cols-1 gap-4 sm:grid-cols-3">
          {STEPS.map((item, index) => (
            <li key={item.num} className={`animate-fadeUp delay-${index + 2} group relative overflow-hidden rounded-3xl border border-line bg-surface/80 p-6 transition-all hover:-translate-y-1 hover:shadow-glow sm:p-7`}>
              <div className={`absolute inset-0 bg-gradient-to-br ${item.tint} opacity-0 transition-opacity group-hover:opacity-100`} aria-hidden="true" />
              <div className="relative">
                <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-2xl transition-transform group-hover:scale-110 group-hover:-rotate-6" aria-hidden="true">{item.icon}</span>
                <span className="text-brand mb-1 block text-xs font-extrabold uppercase tracking-widest">Step {item.num}</span>
                <h2 className="mb-1 text-lg font-bold text-ink">{item.title}</h2>
                <p className="text-sm leading-relaxed text-muted">{item.sub}</p>
              </div>
            </li>
          ))}
        </ol>
      </main>
    </div>
  );
}
