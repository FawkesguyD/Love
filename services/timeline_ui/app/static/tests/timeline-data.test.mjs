import assert from "node:assert/strict";
import test from "node:test";

import {
  buildImageUrl,
  extractImageId,
  normalizeMoment,
  sortMomentsByDate,
} from "../timeline-data.mjs";

test("extractImageId keeps basename and strips extension", () => {
  assert.equal(extractImageId("first_date-1.jpeg"), "first_date-1");
  assert.equal(extractImageId("photo.webp"), "photo");
  assert.equal(extractImageId("broken.name.jpg"), null);
  assert.equal(extractImageId("../secret.jpg"), null);
});

test("normalizeMoment maps payload and sortMomentsByDate keeps chronological order", () => {
  const normalizedEarly = normalizeMoment({
    _id: "1",
    title: "Early",
    text: "first",
    date: "2026-02-13T10:00:00.000Z",
    images: ["a.jpg"],
    tags: ["love"],
  });

  const normalizedLate = normalizeMoment({
    _id: "2",
    title: "Late",
    date: "2026-02-14T12:00:00.000Z",
    images: ["b.jpg"],
  });

  assert.ok(normalizedEarly);
  assert.ok(normalizedLate);

  const sorted = sortMomentsByDate([normalizedLate, normalizedEarly]);
  assert.deepEqual(
    sorted.map((moment) => moment.id),
    ["1", "2"]
  );

  assert.equal(sorted[0].title, "Early");
  assert.equal(sorted[0].text, "first");
  assert.deepEqual(sorted[0].tags, ["love"]);
});

test("buildImageUrl uses API base and images path", () => {
  assert.equal(
    buildImageUrl("", "/api/images", "second_date-1.jpg"),
    "/api/images/second_date-1"
  );

  assert.equal(
    buildImageUrl("https://example.com", "/api/images", "second_date-1.jpg"),
    "https://example.com/api/images/second_date-1"
  );

  assert.equal(buildImageUrl("", "/api/images", "broken.name.jpg"), null);
});
