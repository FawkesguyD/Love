import assert from "node:assert/strict";
import test from "node:test";

import { buildMomentCardSnapshot } from "../timeline-data.mjs";

test("buildMomentCardSnapshot returns stable markup for timeline card", () => {
  const snapshot = buildMomentCardSnapshot(
    {
      id: "507f1f77bcf86cd799439011",
      title: "First date",
      text: "Coffee, rain, and a warm smile.",
      dateIso: "2026-02-14T18:00:00.000Z",
      images: ["first_date-1.jpg"],
    },
    {
      side: "right",
      formattedDate: "14 Feb 2026, 18:00 UTC",
      imageUrl: "/api/images/first_date-1",
    }
  );

  assert.equal(
    snapshot,
    '<article class="timeline-card side-right"><span class="timeline-dot" aria-hidden="true"></span><p class="timeline-date">14 Feb 2026, 18:00 UTC</p><h3 class="timeline-card-title">First date</h3><p class="timeline-text">Coffee, rain, and a warm smile.</p><figure class="timeline-image-wrap"><img class="timeline-image" src="/api/images/first_date-1" alt="First date" loading="lazy" decoding="async" /></figure></article>'
  );
});
