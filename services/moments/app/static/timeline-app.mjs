import {
  buildDayKey,
  buildImageUrl,
  formatDayLabel,
  formatMomentDateTime,
  isSummaryMoment,
  normalizeMoment,
  sortMomentsByDate,
} from "./timeline-data.mjs";

const DEFAULT_CONFIG = {
  cardsListEndpoint: "/api/cards",
  cardDetailsEndpoint: "/api/cards/{id}",
  imagesEndpoint: "/api/images",
  requestTimeoutMs: 6000,
  cacheTtlMs: 45000,
  maxMoments: 500,
  batchSize: 16,
};

const FALLBACK_CARDS_LIST_ENDPOINT = "/api/v1/cards";
const FALLBACK_CARD_DETAILS_ENDPOINT = "/api/v1/cards/{id}";
const MAX_REQUEST_RETRIES = 2;

class HttpError extends Error {
  constructor(status, payload) {
    const message = payload?.error?.message || payload?.detail || `HTTP ${status}`;
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.payload = payload;
  }
}

const state = {
  config: readTimelineConfig(),
  moments: [],
  renderIndex: 0,
  lastRenderedDay: null,
  revealObserver: null,
  sentinelObserver: null,
};

const elements = {
  root: document.getElementById("timeline-app"),
  timeline: document.getElementById("timeline"),
  status: document.getElementById("timeline-status"),
  sentinel: document.getElementById("timeline-sentinel"),
};

function readTimelineConfig() {
  const injected = window.__TIMELINE_CONFIG__;
  if (!injected || typeof injected !== "object") {
    return { ...DEFAULT_CONFIG };
  }

  const merged = {
    ...DEFAULT_CONFIG,
    ...injected,
  };

  return {
    cardsListEndpoint: String(merged.cardsListEndpoint || DEFAULT_CONFIG.cardsListEndpoint).trim(),
    cardDetailsEndpoint: String(merged.cardDetailsEndpoint || DEFAULT_CONFIG.cardDetailsEndpoint).trim(),
    imagesEndpoint: String(merged.imagesEndpoint || DEFAULT_CONFIG.imagesEndpoint).trim(),
    requestTimeoutMs: Number(merged.requestTimeoutMs) > 0 ? Number(merged.requestTimeoutMs) : DEFAULT_CONFIG.requestTimeoutMs,
    cacheTtlMs: Number(merged.cacheTtlMs) > 0 ? Number(merged.cacheTtlMs) : DEFAULT_CONFIG.cacheTtlMs,
    maxMoments: Number(merged.maxMoments) > 0 ? Number(merged.maxMoments) : DEFAULT_CONFIG.maxMoments,
    batchSize: Number(merged.batchSize) > 0 ? Number(merged.batchSize) : DEFAULT_CONFIG.batchSize,
  };
}

function uniqueStrings(values) {
  return [...new Set(values.filter((value) => typeof value === "string" && value.trim()))];
}

function buildListEndpointCandidates(config) {
  return uniqueStrings([config.cardsListEndpoint, FALLBACK_CARDS_LIST_ENDPOINT]);
}

function buildDetailsEndpointCandidates(config) {
  return uniqueStrings([config.cardDetailsEndpoint, FALLBACK_CARD_DETAILS_ENDPOINT]);
}

function cacheKey(config) {
  return `moments.timeline.cache::${config.cardsListEndpoint}`;
}

function updateStatus(message) {
  if (elements.status) {
    elements.status.textContent = message;
  }
}

function resolveUrl(pathOrUrl, params = null) {
  const url = new URL(pathOrUrl, window.location.origin);
  if (params && typeof params === "object") {
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined || value === "") {
        continue;
      }
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

async function fetchJson(url, { timeoutMs, attempts }) {
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(url, {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
        signal: controller.signal,
      });

      let payload = null;
      try {
        payload = await response.json();
      } catch (_parseError) {
        payload = null;
      }

      if (!response.ok) {
        throw new HttpError(response.status, payload);
      }

      return payload;
    } catch (error) {
      lastError = error;

      const isRetryableNetworkError = error?.name === "AbortError" || error instanceof TypeError;
      const isRetryableHttpError = error instanceof HttpError && error.status >= 500;
      const canRetry = attempt < attempts && (isRetryableNetworkError || isRetryableHttpError);

      if (!canRetry) {
        throw error;
      }
    } finally {
      window.clearTimeout(timer);
    }
  }

  throw lastError || new Error("Request failed");
}

async function fetchAllMomentsFromEndpoint(endpoint, config) {
  const allMoments = [];
  const seenCursors = new Set();
  let cursor = null;

  while (allMoments.length < config.maxMoments) {
    const pageUrl = resolveUrl(endpoint, {
      limit: 100,
      order: "asc",
      cursor,
    });

    const payload = await fetchJson(pageUrl.toString(), {
      timeoutMs: config.requestTimeoutMs,
      attempts: MAX_REQUEST_RETRIES,
    });

    const pageMoments = Array.isArray(payload?.moments) ? payload.moments : [];
    allMoments.push(...pageMoments);

    const nextCursor = typeof payload?.nextCursor === "string" && payload.nextCursor ? payload.nextCursor : null;
    if (!nextCursor || seenCursors.has(nextCursor)) {
      break;
    }

    seenCursors.add(nextCursor);
    cursor = nextCursor;
  }

  return allMoments.slice(0, config.maxMoments);
}

function expandDetailsEndpoint(template, momentId) {
  const safeId = encodeURIComponent(momentId);
  if (template.includes("{id}")) {
    return template.replace("{id}", safeId);
  }

  const trimmed = template.replace(/\/+$/, "");
  return `${trimmed}/${safeId}`;
}

async function fetchMomentById(momentId, config) {
  const candidates = buildDetailsEndpointCandidates(config);
  let lastError = null;

  for (const endpointTemplate of candidates) {
    const detailUrl = resolveUrl(expandDetailsEndpoint(endpointTemplate, momentId));

    try {
      return await fetchJson(detailUrl.toString(), {
        timeoutMs: config.requestTimeoutMs,
        attempts: MAX_REQUEST_RETRIES,
      });
    } catch (error) {
      lastError = error;
      if (error instanceof HttpError && error.status === 404) {
        continue;
      }
      throw error;
    }
  }

  if (lastError) {
    throw lastError;
  }

  return null;
}

async function mapWithConcurrency(items, concurrency, mapper) {
  const result = new Array(items.length);
  let cursor = 0;

  async function worker() {
    while (cursor < items.length) {
      const itemIndex = cursor;
      cursor += 1;
      result[itemIndex] = await mapper(items[itemIndex], itemIndex);
    }
  }

  const workerCount = Math.max(1, Math.min(concurrency, items.length));
  const workers = Array.from({ length: workerCount }, () => worker());
  await Promise.all(workers);
  return result;
}

async function hydrateSummaryMoments(rawMoments, config) {
  const summaryCount = rawMoments.filter((moment) => isSummaryMoment(moment)).length;
  if (summaryCount === 0) {
    return rawMoments;
  }

  updateStatus("Loading missing card details...");

  return mapWithConcurrency(rawMoments, 6, async (moment) => {
    if (!isSummaryMoment(moment)) {
      return moment;
    }

    const momentId = String(moment._id || "").trim();
    if (!momentId) {
      return moment;
    }

    try {
      const fullMoment = await fetchMomentById(momentId, config);
      return fullMoment || moment;
    } catch (_error) {
      return moment;
    }
  });
}

async function fetchTimelineMoments(config) {
  const listCandidates = buildListEndpointCandidates(config);
  let lastError = null;

  for (const endpoint of listCandidates) {
    try {
      const rawMoments = await fetchAllMomentsFromEndpoint(endpoint, config);
      return hydrateSummaryMoments(rawMoments, config);
    } catch (error) {
      lastError = error;
      if (error instanceof HttpError && error.status === 404) {
        continue;
      }
      throw error;
    }
  }

  throw lastError || new Error("Cards endpoint is unavailable");
}

function normalizeTimelineMoments(rawMoments) {
  const normalized = rawMoments
    .map((moment) => normalizeMoment(moment))
    .filter((moment) => moment !== null)
    .filter((moment) => moment.visibility !== "draft");

  return sortMomentsByDate(normalized);
}

function readCachedMoments(config) {
  try {
    const raw = sessionStorage.getItem(cacheKey(config));
    if (!raw) {
      return null;
    }

    const payload = JSON.parse(raw);
    if (!payload || typeof payload !== "object") {
      return null;
    }

    const savedAt = Number(payload.savedAt);
    const moments = payload.moments;
    if (!Number.isFinite(savedAt) || !Array.isArray(moments)) {
      return null;
    }

    if (Date.now() - savedAt > config.cacheTtlMs) {
      return null;
    }

    return moments;
  } catch (_error) {
    return null;
  }
}

function cacheMoments(config, moments) {
  try {
    const payload = {
      savedAt: Date.now(),
      moments,
    };

    sessionStorage.setItem(cacheKey(config), JSON.stringify(payload));
  } catch (_error) {
    // Ignore cache failures.
  }
}

function clearTimelineContent() {
  elements.timeline.textContent = "";
  state.renderIndex = 0;
  state.lastRenderedDay = null;
}

function renderLoadingState() {
  clearTimelineContent();

  const skeleton = document.createElement("div");
  skeleton.className = "timeline-skeleton";

  for (let index = 0; index < 4; index += 1) {
    const card = document.createElement("article");
    card.className = `timeline-skeleton-card ${index % 2 === 0 ? "side-left" : "side-right"}`;
    skeleton.append(card);
  }

  elements.timeline.append(skeleton);
  updateStatus("Loading timeline...");
}

function renderPanel({ title, message, buttonLabel, onButtonClick }) {
  clearTimelineContent();

  const panel = document.createElement("section");
  panel.className = "timeline-panel";
  panel.setAttribute("role", "status");

  const heading = document.createElement("h2");
  heading.textContent = title;
  panel.append(heading);

  const body = document.createElement("p");
  body.textContent = message;
  panel.append(body);

  if (buttonLabel && typeof onButtonClick === "function") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-retry";
    button.textContent = buttonLabel;
    button.addEventListener("click", onButtonClick);
    panel.append(button);
  }

  elements.timeline.append(panel);
}

function createDayDivider(dayIso) {
  const divider = document.createElement("section");
  divider.className = "timeline-day";

  const label = document.createElement("h2");
  label.className = "timeline-day-label";
  label.textContent = formatDayLabel(dayIso);
  divider.append(label);

  return divider;
}

function createImageElement(moment) {
  const imageFilename = moment.images[0];
  const imageUrl = buildImageUrl(state.config.imagesEndpoint, imageFilename);

  const figure = document.createElement("figure");
  figure.className = "timeline-image-wrap";

  if (!imageUrl) {
    const fallback = document.createElement("div");
    fallback.className = "timeline-image-fallback";
    fallback.textContent = "Photo unavailable";
    figure.append(fallback);
    return figure;
  }

  figure.classList.add("is-loading");

  const image = document.createElement("img");
  image.className = "timeline-image";
  image.src = imageUrl;
  image.alt = moment.title;
  image.loading = "lazy";
  image.decoding = "async";

  image.addEventListener("load", () => {
    figure.classList.remove("is-loading");
  });

  image.addEventListener("error", () => {
    figure.classList.remove("is-loading");
    figure.textContent = "";

    const fallback = document.createElement("div");
    fallback.className = "timeline-image-fallback";
    fallback.textContent = "Photo unavailable";
    figure.append(fallback);
  });

  figure.append(image);
  return figure;
}

function attachRevealAnimation(card) {
  if (!state.revealObserver) {
    card.classList.add("is-visible");
    return;
  }

  state.revealObserver.observe(card);
}

function createMomentCard(moment, index) {
  const side = index % 2 === 0 ? "left" : "right";

  const card = document.createElement("article");
  card.className = `timeline-card side-${side}`;
  card.setAttribute("role", "listitem");
  card.tabIndex = 0;
  card.dataset.index = String(index);

  const dot = document.createElement("span");
  dot.className = "timeline-dot";
  dot.setAttribute("aria-hidden", "true");
  card.append(dot);

  const dateNode = document.createElement("p");
  dateNode.className = "timeline-date";
  dateNode.textContent = formatMomentDateTime(moment.dateIso);
  card.append(dateNode);

  const title = document.createElement("h3");
  title.className = "timeline-card-title";
  title.textContent = moment.title;
  card.append(title);

  if (moment.text) {
    const text = document.createElement("p");
    text.className = "timeline-text";
    text.textContent = moment.text;
    card.append(text);
  }

  card.append(createImageElement(moment));

  attachRevealAnimation(card);
  return card;
}

function updateSentinelVisibility() {
  if (!elements.sentinel) {
    return;
  }

  const hasMore = state.renderIndex < state.moments.length;
  elements.sentinel.hidden = !hasMore;
}

function appendBatch() {
  if (state.renderIndex >= state.moments.length) {
    updateSentinelVisibility();
    return;
  }

  const fragment = document.createDocumentFragment();
  const batchSize = Math.max(1, state.config.batchSize);
  const endIndex = Math.min(state.renderIndex + batchSize, state.moments.length);

  for (let index = state.renderIndex; index < endIndex; index += 1) {
    const moment = state.moments[index];
    const dayKey = buildDayKey(moment.dateIso);

    if (dayKey !== state.lastRenderedDay) {
      fragment.append(createDayDivider(moment.dateIso));
      state.lastRenderedDay = dayKey;
    }

    fragment.append(createMomentCard(moment, index));
  }

  state.renderIndex = endIndex;
  elements.timeline.append(fragment);
  updateSentinelVisibility();
}

function renderMoments(moments) {
  clearTimelineContent();
  state.moments = moments;

  if (moments.length === 0) {
    renderPanel({
      title: "No events yet",
      message: "Create your first card to start the timeline.",
    });
    updateStatus("Timeline is empty");
    return;
  }

  appendBatch();
  updateStatus(`Timeline loaded: ${moments.length} moments`);
}

function setupObservers() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    state.revealObserver = null;
  } else {
    state.revealObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) {
            continue;
          }

          entry.target.classList.add("is-visible");
          state.revealObserver?.unobserve(entry.target);
        }
      },
      {
        threshold: 0.18,
        rootMargin: "0px 0px -10% 0px",
      }
    );
  }

  if (elements.sentinel) {
    state.sentinelObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            appendBatch();
          }
        }
      },
      {
        rootMargin: "220px 0px 220px 0px",
      }
    );

    state.sentinelObserver.observe(elements.sentinel);
  }
}

function setupKeyboardNavigation() {
  elements.timeline.addEventListener("keydown", (event) => {
    const card = event.target.closest(".timeline-card");
    if (!card) {
      return;
    }

    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }

    const allCards = [...elements.timeline.querySelectorAll(".timeline-card")];
    const currentIndex = allCards.indexOf(card);
    if (currentIndex === -1) {
      return;
    }

    const nextIndex = event.key === "ArrowDown" ? currentIndex + 1 : currentIndex - 1;
    const target = allCards[nextIndex];
    if (!target) {
      return;
    }

    event.preventDefault();
    target.focus();
  });
}

function formatErrorMessage(error) {
  if (error instanceof HttpError) {
    if (error.status === 404) {
      return "Cards API route is not available. Check Traefik routing for /api/cards.";
    }

    if (error.status >= 500) {
      return "Cards API is temporarily unavailable. Please retry in a few seconds.";
    }

    return error.message || "Cards API rejected the request.";
  }

  if (error?.name === "AbortError") {
    return "Request timed out. Please retry.";
  }

  return "Failed to load timeline. Please retry.";
}

async function refreshFromNetwork({ useLoadingState }) {
  if (useLoadingState) {
    renderLoadingState();
  }

  try {
    const rawMoments = await fetchTimelineMoments(state.config);
    const moments = normalizeTimelineMoments(rawMoments);

    renderMoments(moments);
    cacheMoments(state.config, rawMoments);
  } catch (error) {
    const hasVisibleMoments = state.moments.length > 0;
    if (hasVisibleMoments) {
      updateStatus(`Timeline refresh failed: ${formatErrorMessage(error)}`);
      return;
    }

    renderPanel({
      title: "Could not load timeline",
      message: formatErrorMessage(error),
      buttonLabel: "Retry",
      onButtonClick: () => {
        void refreshFromNetwork({ useLoadingState: true });
      },
    });

    updateStatus("Timeline failed to load");
  }
}

async function bootstrap() {
  if (!elements.root || !elements.timeline) {
    return;
  }

  setupObservers();
  setupKeyboardNavigation();

  const cachedMoments = readCachedMoments(state.config);
  if (cachedMoments) {
    const normalizedCached = normalizeTimelineMoments(cachedMoments);
    renderMoments(normalizedCached);
    updateStatus("Loaded cached timeline, refreshing data...");
    void refreshFromNetwork({ useLoadingState: false });
    return;
  }

  await refreshFromNetwork({ useLoadingState: true });
}

void bootstrap();
