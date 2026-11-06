"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Studio is a step of the Make-an-ad flow now. Old links go there: /studio opens the flow with Studio chosen, /studio?job=<id> reopens that video.
export default function StudioPage() {
  const router = useRouter();
  useEffect(() => {
    const job = new URLSearchParams(window.location.search).get("job") ?? "";
    router.replace(/^[0-9a-f]{32}$/.test(job) ? `/ads/create?studio=${job}` : "/ads/create?style=studio");
  }, [router]);
  return <p className="py-16 text-center text-sm text-muted" aria-live="polite">Opening…</p>;
}
