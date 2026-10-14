import Link from "next/link";

const STEPS = [
  { num: "01", title: "Paste your website", sub: "We read it and pull out your business name, offer, phone number and best photos." },
  { num: "02", title: "Pick a goal and style", sub: "Brand awareness, an offer, visits or an event, for a taxi screen, Reel or Short." },
  { num: "03", title: "Get your video ad", sub: "One short video made from one prompt, with your details added as clean text." },
];

// Landing page: headline, call to action and the three steps.
export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <nav className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5">
        <span className="text-xl font-bold tracking-tight text-ink">adsify</span>
        <Link href="/ads" className="rounded-lg px-4 py-2 text-sm font-medium text-accent">Ads →</Link>
      </nav>

      <main className="flex flex-1 flex-col items-center justify-center px-6 pb-20">
        <div className="w-full max-w-2xl space-y-8 text-center">
          <div className="space-y-4">
            <p className="text-sm font-medium uppercase tracking-widest text-muted">Website to video ad</p>
            <h1 className="text-4xl font-bold leading-tight tracking-tight text-ink sm:text-5xl">
              Turn your website into a <span className="text-accent">video ad</span>
            </h1>
            <p className="mx-auto max-w-lg text-lg leading-relaxed text-muted">
              Paste your website, pick a goal, and get a professional short video in minutes. No design skills needed.
            </p>
          </div>
          <div className="flex justify-center pt-2">
            <Link href="/ads/create" className="w-full rounded-xl bg-accent px-8 py-3.5 text-base font-semibold text-white transition-all hover:opacity-90 active:scale-[0.98] sm:w-auto">
              Create your ad
            </Link>
          </div>
        </div>

        <ol className="mt-24 grid w-full max-w-3xl grid-cols-1 gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-3">
          {STEPS.map((item) => (
            <li key={item.num} className="bg-surface p-6 sm:p-8">
              <span className="mb-3 block font-mono text-xs font-bold text-accent">{item.num}</span>
              <h2 className="mb-1 font-semibold text-ink">{item.title}</h2>
              <p className="text-sm leading-relaxed text-muted">{item.sub}</p>
            </li>
          ))}
        </ol>
      </main>
    </div>
  );
}
