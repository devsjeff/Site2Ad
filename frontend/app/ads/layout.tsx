import Link from "next/link";

// Layout shared by the ad pages.
export default function AdsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <nav className="sticky top-0 z-20 border-b border-line bg-background/85 px-6 py-4 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <Link href="/" className="flex items-center gap-2 text-sm font-medium text-muted transition-colors hover:text-ink">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M10 3L5 8l5 5" />
            </svg>
            Home
          </Link>
          <span className="text-sm font-bold tracking-tight text-ink">adsify</span>
          <div className="w-12" />
        </div>
      </nav>
      <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-8 md:py-12">{children}</main>
    </div>
  );
}
