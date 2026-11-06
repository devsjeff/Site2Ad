// Run with: npm test   (Node's built-in test runner; Node strips the TypeScript types of flow.ts itself)

import assert from "node:assert/strict";
import { test } from "node:test";
import { effectiveStyle, flowSteps, readDeeplink, stepAfter, stepBefore, studioAllowed } from "./flow.ts";

test("manual ads go type, media, settings, review", () => {
  assert.deepEqual(flowSteps("manual", null, "captions"), ["how", "media", "customize", "review"]);
  assert.deepEqual(flowSteps("manual", null, "studio"), ["how", "media", "customize", "review"]); // a leftover Studio choice changes nothing
});

test("automated ads with website media choose between Caption + QR and Studio", () => {
  assert.deepEqual(flowSteps("auto", "website", "captions"), ["how", "media", "style", "customize", "review"]);
  assert.deepEqual(flowSteps("auto", "website", "studio"), ["how", "media", "style", "studio"]);
});

test("Studio is only for website media; AI and mixed media use Caption + QR without a style screen", () => {
  assert.equal(studioAllowed("auto", "website"), true);
  for (const source of ["ai", "mixed", null]) {
    assert.equal(studioAllowed("auto", source), false);
    assert.equal(effectiveStyle("auto", source, "studio"), "captions");
    assert.deepEqual(flowSteps("auto", source, "studio"), ["how", "media", "customize", "review"]);
  }
  assert.equal(studioAllowed("manual", "website"), false);
});

test("moving through the steps stays inside the list", () => {
  const steps = flowSteps("auto", "website", "studio");
  assert.equal(stepAfter(steps, "how"), "media");
  assert.equal(stepAfter(steps, "studio"), "studio");
  assert.equal(stepBefore(steps, "studio"), "style");
  assert.equal(stepBefore(steps, "how"), "how");
  assert.equal(stepAfter(steps, "review"), "how"); // a step that is not on this path: start the path again, never an invalid screen
});

test("addresses open the right screen", () => {
  const job = "a".repeat(32);
  assert.deepEqual(readDeeplink(""), { creation: null, source: null, style: "captions", step: "how", scanJob: null, studioJob: null });
  assert.equal(readDeeplink("?mode=manual").creation, "manual");
  assert.equal(readDeeplink("?mode=manual").step, "media");
  assert.equal(readDeeplink("?mode=auto").source, null);
  assert.deepEqual(readDeeplink(`?job=${job}`), { creation: "auto", source: null, style: "captions", step: "media", scanJob: job, studioJob: null });
  assert.equal(readDeeplink("?style=studio").style, "studio");
  assert.equal(readDeeplink(`?studio=${job}`).step, "studio");
  assert.equal(readDeeplink(`?studio=${job}`).studioJob, job);
  assert.equal(readDeeplink("?studio=nope").step, "how"); // not a job id: ignored
  assert.equal(readDeeplink("?mode=banana").creation, null);
});
