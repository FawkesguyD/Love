import assert from "node:assert/strict";
import test from "node:test";

import {
  formatCountdownValue,
  getNextValentineTargetUtcMs,
  splitRemainingDuration,
} from "../lib/timer-utils.mjs";

test("getNextValentineTargetUtcMs returns current-year target before Feb 14", () => {
  const reference = Date.UTC(2026, 0, 20, 12, 0, 0, 0);
  const target = getNextValentineTargetUtcMs(reference);

  assert.equal(target, Date.UTC(2026, 1, 14, 0, 0, 0, 0));
});

test("getNextValentineTargetUtcMs rolls to next year after Feb 14", () => {
  const reference = Date.UTC(2026, 1, 16, 12, 0, 0, 0);
  const target = getNextValentineTargetUtcMs(reference);

  assert.equal(target, Date.UTC(2027, 1, 14, 0, 0, 0, 0));
});

test("splitRemainingDuration and formatCountdownValue format output", () => {
  const parts = splitRemainingDuration(90061000);

  assert.deepEqual(parts, {
    days: 1,
    hours: 1,
    minutes: 1,
    seconds: 1,
    totalMs: 90061000,
  });

  assert.equal(formatCountdownValue(parts), "1д 1ч 1м 1с");
});
