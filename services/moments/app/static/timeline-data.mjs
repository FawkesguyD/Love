const IMAGE_BASENAME_RE = /^[A-Za-z0-9_-]+$/;

function toUtcDate(dateIso) {
  const date = new Date(dateIso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date;
}

export function extractImageId(filename) {
  if (typeof filename !== "string") {
    return null;
  }

  const normalized = filename.trim();
  if (!normalized) {
    return null;
  }

  if (
    normalized.includes("/") ||
    normalized.includes("\\") ||
    normalized.includes("..") ||
    normalized.includes("\0")
  ) {
    return null;
  }

  const lastDotIndex = normalized.lastIndexOf(".");
  const basename = lastDotIndex > 0 ? normalized.slice(0, lastDotIndex) : normalized;

  if (!basename || basename.includes(".")) {
    return null;
  }

  if (!IMAGE_BASENAME_RE.test(basename)) {
    return null;
  }

  return basename;
}

export function normalizeMoment(rawMoment) {
  if (!rawMoment || typeof rawMoment !== "object") {
    return null;
  }

  const rawId = typeof rawMoment._id === "string" ? rawMoment._id : rawMoment.id;
  if (typeof rawId !== "string" || !rawId.trim()) {
    return null;
  }

  const rawDate = typeof rawMoment.date === "string" ? rawMoment.date : null;
  if (!rawDate) {
    return null;
  }

  const parsedDate = toUtcDate(rawDate);
  if (!parsedDate) {
    return null;
  }

  const title =
    typeof rawMoment.title === "string" && rawMoment.title.trim()
      ? rawMoment.title.trim()
      : "Untitled moment";

  const text = typeof rawMoment.text === "string" ? rawMoment.text.trim() : "";

  const images = Array.isArray(rawMoment.images)
    ? rawMoment.images
        .filter((value) => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean)
    : [];

  const tags = Array.isArray(rawMoment.tags)
    ? rawMoment.tags
        .filter((value) => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean)
    : [];

  return {
    id: rawId.trim(),
    title,
    text,
    dateIso: parsedDate.toISOString(),
    epochMs: parsedDate.getTime(),
    visibility: typeof rawMoment.visibility === "string" ? rawMoment.visibility : "public",
    images,
    tags,
  };
}

export function isSummaryMoment(rawMoment) {
  if (!rawMoment || typeof rawMoment !== "object") {
    return false;
  }

  if (typeof rawMoment._id !== "string" || !rawMoment._id.trim()) {
    return false;
  }

  return typeof rawMoment.title !== "string" || typeof rawMoment.date !== "string";
}

export function sortMomentsByDate(moments) {
  return [...moments].sort((left, right) => {
    const dateDelta = left.epochMs - right.epochMs;
    if (dateDelta !== 0) {
      return dateDelta;
    }

    return left.id.localeCompare(right.id);
  });
}

export function buildDayKey(dateIso) {
  return dateIso.slice(0, 10);
}

export function formatDayLabel(dateIso, locale = "en-GB") {
  const date = toUtcDate(dateIso);
  if (!date) {
    return "Unknown date";
  }

  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatMomentDateTime(dateIso, locale = "en-GB") {
  const date = toUtcDate(dateIso);
  if (!date) {
    return "Unknown time";
  }

  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
}

export function buildImageUrl(imagesEndpoint, filename) {
  const imageId = extractImageId(filename);
  if (!imageId) {
    return null;
  }

  const base = String(imagesEndpoint || "").trim().replace(/\/+$/, "");
  if (!base) {
    return null;
  }

  return `${base}/${encodeURIComponent(imageId)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function buildMomentCardSnapshot(moment, options = {}) {
  const side = options.side === "right" ? "right" : "left";
  const formattedDate = options.formattedDate || formatMomentDateTime(moment.dateIso);
  const imageUrl = options.imageUrl || null;
  const text = moment.text || "";

  const imageBlock = imageUrl
    ? `<img class="timeline-image" src="${escapeHtml(imageUrl)}" alt="${escapeHtml(moment.title)}" loading="lazy" decoding="async" />`
    : '<div class="timeline-image-fallback">Photo unavailable</div>';

  return [
    `<article class="timeline-card side-${side}">`,
    '<span class="timeline-dot" aria-hidden="true"></span>',
    `<p class="timeline-date">${escapeHtml(formattedDate)}</p>`,
    `<h3 class="timeline-card-title">${escapeHtml(moment.title)}</h3>`,
    text ? `<p class="timeline-text">${escapeHtml(text)}</p>` : "",
    `<figure class="timeline-image-wrap">${imageBlock}</figure>`,
    "</article>",
  ].join("");
}
