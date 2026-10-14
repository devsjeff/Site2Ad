// Run with: npm test   (Node's built-in test runner; Node strips the TypeScript types of creative.ts itself)
// The same fixtures are validated by the backend in backend/tests/test_creative.py, so both sides agree on every request.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  buildCreative, buildRequest, callsAiVideo, defaultPrefs, estimatedSeconds, normalizeUrl, qrUrlProblem, readinessProblems, switchMode,
  websiteSlotCount, workflowStages,
} from "./creative.ts";

const fixtures = JSON.parse(readFileSync(new URL("./creative.fixtures.json", import.meta.url), "utf8"));

for (const fixture of fixtures) {
  test(`controls for "${fixture.name}" submit exactly the expected request`, () => {
    assert.deepEqual(buildRequest(fixture.input), fixture.request);
  });
}

test("only the AI modes call the AI video provider, and AI mode never sends website images", () => {
  const prefs = { ...defaultPrefs("website", "https://x.example/"), selectedImageUrls: ["https://x.example/a.jpg"], useUploadedMedia: true };
  for (const mode of ["manual", "website", "ai", "mixed"]) {
    assert.equal(buildCreative(mode, prefs, ["a".repeat(32)]).use_ai_video, callsAiVideo(mode), mode);
  }
  const ai = buildCreative("ai", prefs, ["a".repeat(32)]);
  assert.equal(ai.use_website_images, false);
  assert.deepEqual(ai.selected_image_urls, []);
  assert.deepEqual(ai.media_asset_ids, []);
  assert.equal(buildCreative("manual", prefs, ["a".repeat(32)]).creative_mode, null);
});

test("switching modes keeps the user's own choices", () => {
  const start = { ...defaultPrefs("website", "https://shop.example/"), includeLogo: false, selectedImageUrls: ["https://shop.example/a.jpg"] };
  const ai = switchMode(start, "ai");
  assert.equal(ai.includeLogo, false);
  assert.deepEqual(ai.selectedImageUrls, ["https://shop.example/a.jpg"]); // kept in the UI, never sent in AI mode
  assert.equal(switchMode(ai, "manual").useUploadedMedia, true);
});

test("defaults: QR on when a destination is known", () => {
  assert.equal(defaultPrefs("website", "https://shop.example/").includeQr, true);
  assert.equal(defaultPrefs("website", "https://shop.example/").qrUrl, "https://shop.example/");
  assert.equal(defaultPrefs("ai").includeQr, false);
  assert.equal(defaultPrefs("manual").includeQr, true);
});

test("QR destinations are checked like the backend does", () => {
  for (const good of ["https://shop.example.com/menu?x=1", "http://a.b.example/"]) assert.equal(qrUrlProblem(good), null, good);
  for (const bad of ["", "javascript:alert(1)", "ftp://x.example", "https://localhost/", "https://192.168.1.4/", "https://intranet/", "https://u:p@x.example", "https://a b.example"]) {
    assert.notEqual(qrUrlProblem(bad), null, bad);
  }
  assert.equal(normalizeUrl(" shop.example.com/menu "), "https://shop.example.com/menu");
  assert.equal(normalizeUrl("http://shop.example.com"), "http://shop.example.com");
});

test("readiness explains missing inputs and unavailable AI instead of pretending", () => {
  const base = { prefs: defaultPrefs("manual"), mediaCount: 0, websiteImageCount: 0, aiAvailable: false, aiUnavailableReason: "No key.", hasScan: false };
  assert.deepEqual(readinessProblems({ ...base, mode: "manual", prefs: { ...base.prefs, qrUrl: "https://shop.example/" } }), ["Upload at least one image or video."]);
  assert.ok(readinessProblems({ ...base, mode: "ai", prefs: defaultPrefs("ai") }).includes("No key."));
  assert.ok(readinessProblems({ ...base, mode: "mixed", prefs: defaultPrefs("mixed") }).some((p) => p.includes("website scan")));
  assert.deepEqual(readinessProblems({ ...base, mode: "website", prefs: defaultPrefs("website", "https://s.example/"), hasScan: true, websiteImageCount: 2 }), []);
});

test("website ads use one 3-second slot per image (same rule as the backend)", () => {
  assert.deepEqual([3, 5, 10, 15, 20].map(websiteSlotCount), [1, 2, 3, 5, 7]);
});

test("workflow stages and estimated length follow the mode", () => {
  assert.ok(workflowStages("manual").every((stage) => !stage.includes("AI")));
  assert.ok(workflowStages("website").every((stage) => !stage.includes("AI")));
  assert.ok(workflowStages("ai").some((stage) => stage.includes("no website pictures")));
  const common = { durationSeconds: 15, websiteImageSeconds: 2.5, websiteImageCount: 2, uploadedVideoSeconds: 0, uploadedImageCount: 0 };
  assert.equal(estimatedSeconds({ ...common, mode: "website" }), 15);
  assert.equal(estimatedSeconds({ ...common, mode: "ai" }), 15); // the AI clip is looped to the chosen length
  assert.equal(estimatedSeconds({ ...common, mode: "mixed" }), 20);
  assert.equal(estimatedSeconds({ ...common, mode: "manual", uploadedVideoSeconds: 12, uploadedImageCount: 1 }), 15);
});
