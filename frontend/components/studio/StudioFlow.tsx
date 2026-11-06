"use client";

import React, { useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { stopsPolling } from "@/lib/studio";
import type { ConfigResponse, StudioAssumptions, StudioRequest, StudioResponse } from "@/lib/types";
import { usePolling } from "@/lib/usePolling";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";
import { StudioForm } from "./StudioForm";
import { StudioProgress } from "./StudioProgress";
import { StudioResult } from "./StudioResult";
import { StudioReview } from "./StudioReview";

const JOB_ID = /^[0-9a-f]{32}$/;

// Keeps the job id in the address (without a new history entry) so the page can be reloaded or shared. `param` is "job" on its own page and
// "studio" inside the Make-an-ad flow (where "job" already means the website scan).
function rememberJob(jobId: string | null, param: string) {
  try {
    const url = new URL(window.location.href);
    if (jobId) url.searchParams.set(param, jobId);
    else url.searchParams.delete(param);
    window.history.replaceState(null, "", url.pathname + url.search);
  } catch {
    // The address bar is a convenience only.
  }
}

function jobFromAddress(param: string): string | null {
  try {
    const id = new URL(window.location.href).searchParams.get(param) ?? "";
    return JOB_ID.test(id) ? id : null;
  } catch {
    return null;
  }
}

// The Studio screens in order: form, live progress, review, result. The server owns the state; this page polls it.
interface StudioFlowProps {
  /** The website, when the Make-an-ad flow already asked for it. */
  url?: string;
  /** Go back to the previous screen of the Make-an-ad flow (shown on the first Studio screen). */
  onBack?: () => void;
  /** The address parameter that keeps the job id ("job" on its own page, "studio" inside the Make-an-ad flow). */
  jobParam?: string;
}

export function StudioFlow({ url, onBack, jobParam = "job" }: StudioFlowProps = {}) {
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [round, setRound] = useState(0); // changes after "continue" so polling restarts
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [latest, setLatest] = useState<StudioResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getConfig().then(
      (value) => !cancelled && setConfig(value),
      (error) => !cancelled && setConfigError(errorMessage(error)),
    );
    const saved = jobFromAddress(jobParam);
    if (saved) setJobId(saved);
    return () => { cancelled = true; };
  }, [jobParam]);

  const { data, error: pollError } = usePolling<StudioResponse>({
    fetcher: () => api.studioGet(jobId ?? ""),
    isDone: (value) => stopsPolling(value.status),
    enabled: jobId !== null,
    resetKey: `${jobId ?? ""}:${round}`,
  });
  const job = data ?? (latest && latest.job_id === jobId ? latest : null);

  async function act(work: () => Promise<StudioResponse>) {
    setBusy(true);
    setActionError(null);
    try {
      const next = await work();
      setLatest(next);
      setJobId(next.job_id);
      rememberJob(next.job_id, jobParam);
      setRound((value) => value + 1);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function again() {
    setJobId(null);
    setLatest(null);
    setActionError(null);
    rememberJob(null, jobParam);
  }

  if (configError) return <Alert tone="error" title="Could not reach the server">{configError}</Alert>;
  if (!config) return <div className="flex items-center gap-3 text-sm text-muted"><Spinner /> Loading…</div>;

  if (!jobId) {
    return <StudioForm config={config} busy={busy} error={actionError} url={url} onBack={onBack} onStart={(request: StudioRequest) => act(() => api.studioCreate(request))} />;
  }
  if (pollError && !job) {
    return (
      <div className="space-y-4">
        <Alert tone="error" title="Could not load this video">{errorMessage(pollError)}</Alert>
        <Button variant="secondary" onClick={again}>Start over</Button>
      </div>
    );
  }
  if (!job) return <div className="flex items-center gap-3 text-sm text-muted"><Spinner /> Loading…</div>;

  if (job.status === "review") {
    return (
      <StudioReview key={`${job.job_id}:${round}`} job={job} config={config} busy={busy} error={actionError}
        onCancel={() => act(() => api.studioCancel(job.job_id))}
        onContinue={(assumptions: StudioAssumptions) => act(async () => {
          await api.studioSaveAssumptions(job.job_id, assumptions);
          return api.studioContinue(job.job_id);
        })} />
    );
  }
  if (job.status === "completed") return <StudioResult job={job} onAgain={again} />;
  if (job.status === "failed" || job.status === "cancelled") {
    return (
      <section className="space-y-5 animate-fadeUp">
        <Alert tone={job.status === "failed" ? "error" : "info"} title={job.status === "failed" ? "The video could not be made" : "Cancelled"}>
          {job.error || (job.status === "cancelled" ? "You stopped this video." : "Something went wrong.")}
        </Alert>
        <Button onClick={again}>Try again</Button>
      </section>
    );
  }
  return <StudioProgress job={job} cancelling={busy} onCancel={() => act(() => api.studioCancel(job.job_id))} />;
}
