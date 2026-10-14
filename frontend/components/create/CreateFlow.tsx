"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, errorMessage } from "@/lib/api";
import {
  buildRequest, callsAiVideo, defaultPrefs, estimatedSeconds, normalizeUrl, readinessProblems, showsWebsiteImages, switchMode,
  websiteSlotCount, type CreativePrefs, type ModeId,
} from "@/lib/creative";
import { EMPTY_DRAFT, mergeScan, toOverrides, type BusinessDraft, type DraftField } from "@/lib/draft";
import { usePolling } from "@/lib/usePolling";
import {
  isScanFailure, type AdOptions, type AssetInfo, type BusinessOverrides, type ConfigResponse, type CreationMode, type CreativeMode,
  type JobResponse,
} from "@/lib/types";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { InputField } from "../ui/InputField";
import { CreativeModeStep } from "./CreativeModeStep";
import { ImageUpload } from "./ImageUpload";
import { MediaUpload } from "./MediaUpload";
import { ModeStep } from "./ModeStep";
import { OptionsStep } from "./OptionsStep";
import { PreferencesStep } from "./PreferencesStep";
import { ReviewStep, type EditTarget, type ReviewSummary } from "./ReviewStep";
import { ScanProgress } from "./ScanProgress";

// Screens of the flow. Only the current one is shown (no step counter), so the flow never looks long.
type StepKey = "mode" | "business" | "media" | "creative" | "settings" | "review";

const AUTO_STEPS: StepKey[] = ["mode", "business", "creative", "settings", "review"];
const MANUAL_STEPS: StepKey[] = ["mode", "media", "settings", "review"];

const DEFAULT_OPTIONS: AdOptions = {
  goal: "awareness", platform: "taxi_screen", duration_seconds: 5, style: "cinematic_premium", tone: "friendly",
  special_instructions: "", add_overlays: true,
};

interface ManualDetails {
  name: string;
  offer: string;
  cta: string;
  phone: string;
}

// "1 photo" / "3 photos".
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

// The whole create-ad flow: choose manual or auto, give the content, pick a creative mode, set preferences, review, create.
export function CreateFlow() {
  const router = useRouter();
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [stepKey, setStepKey] = useState<StepKey>("mode");
  const [creation, setCreation] = useState<CreationMode | null>(null);
  const [creativeMode, setCreativeMode] = useState<CreativeMode | null>(null);

  const [url, setUrl] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [firstJob, setFirstJob] = useState<JobResponse | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);

  const [draft, setDraft] = useState<BusinessDraft>(EMPTY_DRAFT);
  const [touched, setTouched] = useState<ReadonlySet<DraftField>>(new Set());
  const [logo, setLogo] = useState<AssetInfo[]>([]);
  const [media, setMedia] = useState<AssetInfo[]>([]);
  const [details, setDetails] = useState<ManualDetails>({ name: "", offer: "", cta: "", phone: "" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [options, setOptions] = useState<AdOptions>(DEFAULT_OPTIONS);
  const [prefs, setPrefs] = useState<CreativePrefs | null>(null);
  const [nameError, setNameError] = useState<string | undefined>();
  const [stepError, setStepError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const mode: ModeId = creation === "manual" ? "manual" : creativeMode ?? "website";
  const steps = creation === "manual" ? MANUAL_STEPS : AUTO_STEPS;

  // --- server options
  useEffect(() => {
    let cancelled = false;
    api.getConfig().then(
      (value) => {
        if (cancelled) return;
        setConfig(value);
        setOptions((current) => (value.compose_durations.includes(current.duration_seconds) ? current : { ...current, duration_seconds: value.compose_durations[0] }));
      },
      (error) => !cancelled && setConfigError(errorMessage(error)),
    );
    return () => { cancelled = true; };
  }, []);

  // Auto ads start in Website Content Priority (the user can still switch on the creative-mode screen).
  const startAuto = useCallback(() => {
    setCreativeMode((current) => current ?? "website");
    setPrefs((current) => current ?? defaultPrefs("website"));
  }, []);

  // --- deep links: /ads/create?mode=manual|auto, and ?job=<id> (the "make another ad" link reuses a scan)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const previous = params.get("job");
    const wanted = params.get("mode");
    if (previous) {
      setCreation("auto");
      startAuto();
      setStepKey("business");
      api.getJob(previous).then(
        (job) => { setFirstJob(job); setJobId(job.job_id); setUrl(job.url); },
        () => undefined,
      );
    } else if (wanted === "manual" || wanted === "auto") {
      setCreation(wanted);
      setStepKey(wanted === "manual" ? "media" : "business");
      if (wanted === "manual") setPrefs(defaultPrefs("manual"));
      else startAuto();
    }
  }, [startAuto]);

  // --- poll the scan
  const polled = usePolling<JobResponse>({
    fetcher: () => api.getJob(jobId ?? ""),
    isDone: (job) => job.is_final,
    enabled: jobId !== null,
    resetKey: jobId ?? "",
  });
  const job = polled.data ?? firstJob;
  const result = job?.result ?? null;
  const draftReady = job !== null && (job.stage === "ad_ready" || job.is_final);
  const scanning = jobId !== null && !draftReady;
  const failed = job !== null && job.is_final && isScanFailure(job.status);
  const scanUsable = result !== null && (result.status === "ok" || result.status === "partial") && job !== null;
  const websiteUrl = result?.home_url || "";

  useEffect(() => {
    if (job?.result) setDraft((current) => mergeScan(current, touched, job.result?.site));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.updated_at, job?.job_id]);

  const startScan = useCallback(async () => {
    const value = url.trim();
    if (!value) { setScanError("Enter your website address first."); return; }
    setScanError(null);
    setFirstJob(null);
    setPrefs((current) => (current ? { ...current, selectedImageUrls: [] } : current));
    try {
      const started = await api.startScrape(value);
      setFirstJob(started);
      setJobId(started.job_id);
    } catch (error) {
      setScanError(errorMessage(error));
    }
  }, [url]);

  // Update one business field in the draft.
  const edit = (field: DraftField, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
    setTouched((current) => new Set(current).add(field));
    if (field === "name") setNameError(undefined);
  };

  const scraped = useMemo(() => (scanUsable ? result?.images ?? [] : []), [scanUsable, result]);
  const usableScraped = scraped.filter((u) => !/\.(svg|gif)(\?|$)/i.test(u));
  const durations = config?.compose_durations ?? [5];

  // Pick a creation mode (manual / auto).
  function chooseCreation(value: CreationMode) {
    setCreation(value);
    setStepError(null);
    if (value === "manual") setPrefs((current) => (current ? switchMode(current, "manual") : defaultPrefs("manual")));
    else startAuto();
  }

  // Pick an auto creative mode, keeping the user's own choices.
  function chooseCreative(value: CreativeMode) {
    setCreativeMode(value);
    setStepError(null);
    setPrefs((current) => (current ? switchMode(current, value) : defaultPrefs(value, websiteUrl)));
  }

  const activePrefs: CreativePrefs = prefs ?? defaultPrefs(mode, websiteUrl);
  const uploadedForMode = mode === "manual" ? media : [];
  const websiteImageCount = showsWebsiteImages(mode)
    ? activePrefs.selectedImageUrls.length || Math.min(usableScraped.length, mode === "website" ? websiteSlotCount(options.duration_seconds) : 2)
    : 0;
  const problems = config
    ? readinessProblems({
      mode, prefs: activePrefs, mediaCount: uploadedForMode.length, websiteImageCount, aiAvailable: config.ai_video_available,
      aiUnavailableReason: config.ai_video_message, hasScan: scanUsable,
    })
    : [];

  // Go to the next screen (with the checks for the screen we leave).
  function next() {
    setStepError(null);
    if (stepKey === "mode") {
      if (!creation) { setStepError("Choose an auto or a manual ad."); return; }
      setStepKey(creation === "manual" ? "media" : "business");
    } else if (stepKey === "business") {
      if (!scanUsable) { setStepError("Scan your website first."); return; }
      if (!draft.name.trim()) { setNameError("We could not find your business name. Enter it."); return; }
      setStepKey("creative");
    } else if (stepKey === "media") {
      if (media.length === 0) { setStepError("Upload at least one image or video."); return; }
      setStepKey("settings");
    } else if (stepKey === "creative") {
      if (!creativeMode) { setStepError("Choose how your ad should be made."); return; }
      if (callsAiVideo(creativeMode) && !config?.ai_video_available) { setStepError(config?.ai_video_message ?? "AI video is not available."); return; }
      if (prefs && !prefs.qrUrl && websiteUrl) setPrefs({ ...prefs, qrUrl: websiteUrl, includeQr: true });
      setStepKey("settings");
    } else if (stepKey === "settings") {
      setStepKey("review");
    }
  }

  // Go one screen back.
  function back() {
    setStepError(null);
    const index = steps.indexOf(stepKey);
    if (index > 0) setStepKey(steps[index - 1]);
  }

  // Jump from the review screen to the screen that holds a value.
  function editFrom(target: EditTarget) {
    if (target === "business") setStepKey(creation === "manual" ? "media" : "business");
    else setStepKey(target);
  }

  // The business details that go with the request.
  function business(): BusinessOverrides {
    if (mode !== "manual") return toOverrides(draft, touched, websiteUrl);
    return {
      name: details.name.trim(), website_url: "", category: "", description: "", phone: details.phone.trim(), address: "",
      offer: details.offer.trim(), cta: details.cta.trim(), services: [], omit: [],
    };
  }

  // Lines for the review screen.
  function summary(): ReviewSummary {
    const lines: string[] = [];
    const picked = activePrefs.selectedImageUrls.length > 0 ? "picked by you" : "chosen automatically";
    const videos = media.filter((m) => m.media_type === "video");
    const images = media.length - videos.length;
    if (mode === "manual") {
      if (images) lines.push(`${plural(images, "uploaded photo")} with gentle motion`);
      if (videos.length) lines.push(`${plural(videos.length, "uploaded video")} (${videos.reduce((s, v) => s + v.duration_seconds, 0).toFixed(1)} s, played in full)`);
    } else if (mode === "website") {
      const slots = websiteSlotCount(options.duration_seconds);
      lines.push(`${plural(websiteImageCount, "original website image")} (${picked}), 3 seconds each`);
      if (websiteImageCount > 0 && websiteImageCount < slots) lines.push(`Repeats in a loop to fill ${slots} slots of 3 seconds`);
      lines.push("No AI-generated footage");
    } else if (mode === "ai") {
      lines.push("AI-generated video made from your scanned business details", "No website pictures", `Looped to ${options.duration_seconds} seconds if the AI clip is shorter`);
    } else {
      lines.push(`Opening: original website image (${picked})`, "Middle: AI-generated video", "Closing: original website image");
    }
    const manual = mode === "manual";
    return {
      name: manual ? details.name : draft.name, offer: manual ? details.offer : draft.offer, cta: manual ? details.cta : draft.cta,
      phone: manual ? details.phone : draft.phone, address: manual ? "" : draft.address, media: lines,
      logo: logo.length ? "Your uploaded logo" : manual ? "" : "From your website, if a usable one is found",
      estimatedSeconds: estimatedSeconds({
        mode, durationSeconds: options.duration_seconds, websiteImageSeconds: config?.website_image_seconds ?? 2.5, websiteImageCount,
        uploadedVideoSeconds: videos.reduce((s, v) => s + v.duration_seconds, 0), uploadedImageCount: images,
      }),
    };
  }

  // Send the request that creates the ad, then open its result page.
  async function create() {
    if (!config || problems.length > 0) return;
    setSubmitting(true);
    setSubmitError(null);
    const request = buildRequest({
      mode, prefs: { ...activePrefs, qrUrl: normalizeUrl(activePrefs.qrUrl) }, options, business: business(),
      jobId: scanUsable && job ? job.job_id : null, hero: null, logoAssetId: logo[0]?.asset_id ?? null,
      mediaAssetIds: mode === "manual" ? media.map((asset) => asset.asset_id) : [],
    });
    try {
      const ad = await api.generateAd(request);
      router.push(`/ads/${ad.ad_id}`);
    } catch (error) {
      setSubmitError(errorMessage(error));
      setSubmitting(false);
    }
  }

  if (configError) {
    return <Alert tone="error" title="The server is not reachable">{configError}</Alert>;
  }
  if (!config) {
    return <p className="py-16 text-center text-sm text-muted" aria-live="polite">Loading…</p>;
  }

  const nav = (label = "Continue", disabled = false) => (
    <div className="flex justify-between">
      {stepKey !== "mode" ? <Button variant="ghost" onClick={back}>Back</Button> : <span />}
      <Button onClick={next} disabled={disabled}>{label}</Button>
    </div>
  );

  return (
    <div className="space-y-8">
      {stepKey === "mode" && (
        <section className="space-y-6 animate-fadeUp">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">Create an ad</h1>
            <p className="mt-1 text-sm text-muted">Start from your website, or build it from your own photos and videos.</p>
          </div>
          <ModeStep modes={config.creative_modes} value={creation} onChange={chooseCreation} />
          {stepError && <Alert tone="error">{stepError}</Alert>}
          {nav("Continue", !creation)}
        </section>
      )}

      {stepKey === "media" && (
        <section className="space-y-6 animate-fadeUp">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">Your media</h1>
            <p className="mt-1 text-sm text-muted">Upload the images or videos the ad is made of. Nothing is scanned and no AI video is generated.</p>
          </div>
          <MediaUpload assets={media} maxFiles={Math.min(config.max_upload_files, 10)} maxVideoMb={Math.round(config.max_video_upload_bytes / (1024 * 1024))} maxVideoSeconds={config.max_video_upload_seconds} onChange={setMedia} onError={setUploadError} />
          <ImageUpload kind="logo" label="Your logo (optional)" hint="Shown in the corner of the video." assets={logo} maxFiles={1} onChange={setLogo} onError={setUploadError} />
          {uploadError && <Alert tone="error">{uploadError}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <InputField label="Business name (optional)" value={details.name} onChange={(v) => setDetails({ ...details, name: v })} maxLength={120} />
            <InputField label="Offer (optional)" value={details.offer} onChange={(v) => setDetails({ ...details, offer: v })} maxLength={160} placeholder="e.g. 20% off this week" />
            <InputField label="Call to action (optional)" value={details.cta} onChange={(v) => setDetails({ ...details, cta: v })} maxLength={80} placeholder="e.g. Scan to order" />
            <InputField label="Phone (optional)" value={details.phone} onChange={(v) => setDetails({ ...details, phone: v })} maxLength={40} inputMode="tel" />
          </div>
          {stepError && <Alert tone="error">{stepError}</Alert>}
          {nav("Continue", media.length === 0)}
        </section>
      )}

      {stepKey === "business" && (
        <section className="space-y-6 animate-fadeUp">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">Your website</h1>
            <p className="mt-1 text-sm text-muted">Paste your website. We scan it for your business name, images and details.</p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <InputField label="Website address" value={url} onChange={setUrl} placeholder="yourbusiness.com" inputMode="url" autoComplete="url" disabled={scanning} error={scanError ?? undefined} />
            </div>
            <Button onClick={startScan} loading={scanning} disabled={!url.trim()}>{result ? "Scan again" : "Scan website"}</Button>
          </div>

          {jobId !== null && !(job?.is_final ?? false) && <ScanProgress job={job} />}
          {polled.error !== null && polled.error !== undefined && <Alert tone="error" title="We lost contact with the server">{errorMessage(polled.error)}</Alert>}
          {failed && job && <Alert tone="warn" title="We could not read that website">{job.result?.message || job.message} Check the address, or create a manual ad from your own photos and videos.</Alert>}
          {job?.is_final && !failed && job.result?.status === "partial" && <Alert tone="info">{job.result.message}</Alert>}
          {result?.flags.includes("browser_unavailable") && (
            <Alert tone="warn" title="Some content may be missing">This website needs JavaScript, but the server&apos;s browser renderer is not available, so only the plain page was read.</Alert>
          )}

          {scanUsable && draftReady && (
            <>
              {(!result?.site.name || touched.has("name")) && (
                <InputField label="Business name" required value={draft.name} onChange={(v) => edit("name", v)} maxLength={120} error={nameError} helpText="Your website did not show a clear business name." />
              )}
              {(result?.site.offer || touched.has("offer")) && (
                <InputField label="Offer shown on the video" value={draft.offer} onChange={(v) => edit("offer", v)} maxLength={160} helpText="Found on your website. Check it belongs to your business, or clear it to leave it out." />
              )}
              <InputField label="Call to action" value={draft.cta} onChange={(v) => edit("cta", v)} maxLength={80} placeholder="e.g. Order now" helpText={draft.cta && !touched.has("cta") ? "Found on your website. Edit or clear it." : "Shown on the video, e.g. Order now or Book a table."} />
            </>
          )}
          {stepError && <Alert tone="error">{stepError}</Alert>}
          {nav("Continue", !scanUsable || scanning)}
        </section>
      )}

      {stepKey === "creative" && (
        <section className="space-y-6 animate-fadeUp">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">How should your ad be made?</h1>
            <p className="mt-1 text-sm text-muted">We found {plural(usableScraped.length, "usable image")} on your website.</p>
          </div>
          <CreativeModeStep modes={config.creative_modes} value={creativeMode} onChange={chooseCreative} aiAvailable={config.ai_video_available} aiMessage={config.ai_video_message} />
          {stepError && <Alert tone="error">{stepError}</Alert>}
          {nav("Continue", !creativeMode)}
        </section>
      )}

      {stepKey === "settings" && (
        <section className="space-y-8 animate-fadeUp">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">Almost done</h1>
            <p className="mt-1 text-sm text-muted">Change anything you like; only the options that fit your ad are shown.</p>
          </div>
          <PreferencesStep
            mode={mode} prefs={activePrefs} onChange={setPrefs} websiteImages={scraped} photos={[]}
            hasLogo={logo.length > 0} hasVideo={mode === "manual" && media.some((m) => m.media_type === "video")} durationSeconds={options.duration_seconds}
          />
          <OptionsStep
            config={config} options={options} onChange={setOptions} durations={durations} aiControls={callsAiVideo(mode)}
            durationNote={
              callsAiVideo(mode) ? `The AI model makes clips of up to ${config.max_video_seconds} seconds; shorter clips loop to fill your chosen length.`
                : mode === "manual" && media.some((m) => m.media_type === "video") ? "Uploaded videos play in full; the length applies to photos."
                  : mode === "website" ? "Each website image plays for 3 seconds." : undefined
            }
            overlayLabel={mode === "manual" ? "Show my business name, offer and call to action" : undefined}
          />
          {nav("Review")}
        </section>
      )}

      {stepKey === "review" && (
        <section className="space-y-6 animate-fadeUp">
          <h1 className="text-2xl font-bold tracking-tight text-ink">Ready to create</h1>
          <ReviewStep config={config} mode={mode} prefs={{ ...activePrefs, qrUrl: normalizeUrl(activePrefs.qrUrl) }} options={options} summary={summary()} problems={problems} onEdit={editFrom} />
          {submitError && <Alert tone="error" title="Could not start your ad">{submitError}</Alert>}
          <div className="flex justify-between">
            <Button variant="ghost" onClick={back} disabled={submitting}>Back</Button>
            <Button onClick={create} loading={submitting} disabled={problems.length > 0}>Create my ad</Button>
          </div>
        </section>
      )}
    </div>
  );
}
