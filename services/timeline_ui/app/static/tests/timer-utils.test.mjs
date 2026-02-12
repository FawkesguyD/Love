import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateElapsedParts,
  formatElapsedValue,
  parseTimerPayload,
  splitElapsedDuration,
} from "../lib/timer-utils.mjs";

test("splitElapsedDuration and formatElapsedValue render elapsed timer", () => {
  const parts = splitElapsedDuration(90061);

  assert.deepEqual(parts, {
    days: 1,
    hours: 1,
    minutes: 1,
    seconds: 1,
    totalSeconds: 90061,
  });

  assert.equal(formatElapsedValue(parts), "1д 1ч 1м 1с");
});

test("parseTimerPayload reads totalSeconds and since fields", () => {
  const parsed = parseTimerPayload(
    {
      since: "2025-03-06T18:00:00.000Z",
      now: "2026-02-13T00:00:00.000Z",
      totalSeconds: 100,
    },
    Date.UTC(2026, 1, 13, 0, 0, 0, 0)
  );

  assert.equal(parsed.totalSeconds, 100);
  assert.equal(parsed.sinceIso, "2025-03-06T18:00:00.000Z");
});

test("parseTimerPayload falls back to elapsed object when totalSeconds missing", () => {
  const parsed = parseTimerPayload({
    elapsed: {
      years: 0,
      days: 1,
      hours: 2,
      minutes: 3,
      seconds: 4,
    },
  });

  assert.equal(parsed.totalSeconds, 93784);
});

test("calculateElapsedParts exposes years when anniversary is crossed", () => {
  const parts = calculateElapsedParts("2025-03-06T18:00:00.000Z", "2026-03-06T18:00:01.000Z");

  assert.equal(parts.years, 1);
  assert.equal(parts.days, 0);
  assert.equal(parts.hours, 0);
  assert.equal(parts.minutes, 0);
  assert.equal(parts.seconds, 1);
  assert.equal(formatElapsedValue(parts), "1г 0д 0ч 0м 1с");
});
