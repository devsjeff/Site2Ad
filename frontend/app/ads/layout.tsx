import Link from "next/link";
import { Logo } from "@/components/ui/Logo";

// Layout shared by the ad pages.
export default function AdsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <nav className="glass sticky top-0 z-20 border-b border-line/70 px-5 py-3">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <Logo />
          <Link href="/ads" className="rounded-full border border-line bg-surface/70 px-4 py-1.5 text-xs font-semibold text-muted transition-all hover:border-accent hover:text-accent">
            My ads
          </Link>
        </div>
      </nav>
      <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-8 md:py-12">{children}</main>
    </div>
  );
}
