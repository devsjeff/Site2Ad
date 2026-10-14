"use client";

import { useEffect, useRef, useState } from "react";

interface PollOptions<T> {
  /** Fetch the latest value. */
  fetcher: () => Promise<T>;
  /** Stop polling when this returns true. */
  isDone: (value: T) => boolean;
  /** Set to false to pause (for example before there is an id). */
  enabled: boolean;
  /** Identifies what is polled (an id); a new key restarts polling from scratch. */
  resetKey: string;
  /** First delay in ms; it grows by 25% each round up to maxMs. */
  startMs?: number;
  maxMs?: number;
  /** Stop and report after this many failures in a row. */
  maxFailures?: number;
}

interface PollState<T> {
  data: T | null;
  error: unknown;
  done: boolean;
}

/** Poll with gentle back-off. Cancels on unmount, ignores one-off network blips, never overlaps requests. */
export function usePolling<T>({ fetcher, isDone, enabled, resetKey, startMs = 1200, maxMs = 5000, maxFailures = 6 }: PollOptions<T>): PollState<T> {
  const [state, setState] = useState<PollState<T>>({ data: null, error: null, done: false });
  const fetcherRef = useRef(fetcher);
  const doneRef = useRef(isDone);
  fetcherRef.current = fetcher;
  doneRef.current = isDone;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = startMs;
    let failures = 0;

    // One polling round: fetch, store the result, schedule the next round a little later.
    async function tick() {
      try {
        const value = await fetcherRef.current();
        if (cancelled) return;
        failures = 0;
        const finished = doneRef.current(value);
        setState({ data: value, error: null, done: finished });
        if (finished) return;
      } catch (error) {
        if (cancelled) return;
        failures += 1;
        if (failures >= maxFailures) {
          setState((previous) => ({ ...previous, error, done: true }));
          return;
        }
      }
      delay = Math.min(delay * 1.25, maxMs);
      timer = setTimeout(tick, delay);
    }

    setState({ data: null, error: null, done: false });
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, resetKey, startMs, maxMs, maxFailures]);

  return state;
}
