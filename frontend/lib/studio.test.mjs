// Run with: npm test   (Node's built-in test runner; Node strips the TypeScript types of studio.ts itself)

import assert from "node:assert/strict";
import { test } from "node:test";
import { fitLength, isWorking, lengthChoices, playerShape, seconds, splitLines, stopsPolling } from "./studio.ts";

test("lengths below the minimum for a video type are not offered", () => {
  assert.deepEqual(lengthChoices(10), [10, 15, 20, 30, 45, 60]);
  assert.deepEqual(lengthChoices(25), [30, 45, 60]);
});

test("changing the video type keeps a valid length", () => {
  assert.equal(fitLength(20, 10), 20);
  assert.equal(fitLength(15, 25), 30);
  assert.equal(fitLength(20, 90), 90);
});

test("facts are trimmed, de-duplicated and limited", () => {
  assert.deepEqual(splitLines("  a \n\nA\r\nb"), ["a", "b"]);
  assert.equal(splitLines("1\n2\n3\n4\n5\n6\n7").length, 5);
  assert.deepEqual(splitLines("   "), []);
});

test("polling stops only when the person has to act or the job is over", () => {
  for (const status of ["review", "completed", "failed", "cancelled"]) assert.equal(stopsPolling(status), true);
  for (const status of ["queued", "running"]) {
    assert.equal(stopsPolling(status), false);
    assert.equal(isWorking(status), true);
  }
});

test("the player follows the video shape and seconds read well", () => {
  assert.match(playerShape("9:16"), /9\/16/);
  assert.match(playerShape("1:1"), /square/);
  assert.match(playerShape("16:9"), /video/);
  assert.equal(seconds(4), "4 s");
  assert.equal(seconds(4.25), "4.3 s");
});
