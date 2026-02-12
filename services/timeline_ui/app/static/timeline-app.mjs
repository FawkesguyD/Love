import { buildApiConfig, getCardById, getCardsList, getTimer, HttpError } from "./lib/api-client.mjs";
import { createMomentCard } from "./components/timeline-item.mjs";
import { clearContainer, renderEmptyState, renderErrorState, renderLoadingState } from "./components/states.mjs";
import { buildImageUrl, isSummaryMoment, normalizeMoment, sortMomentsByDate } from "./timeline-data.mjs";
import {
  calculateElapsedParts,
  formatElapsedValue,
  formatSinceLabel,
  parseTimerPayload,
} from "./lib/timer-utils.mjs";

const DEFAULT_CONFIG = {
  apiBaseUrl: "",
  cardsListPath: "/api/cards",
  cardByIdPathTemplate: "/api/cards/{id}",
  imagesPath: "/api/images",
  timerPath: "/api/timer",
  requestTimeoutMs: 6000,
  cacheTtlMs: 45000,
  maxMoments: 500,
  batchSize: 16,
  maxRetries: 2,
  timerSyncIntervalMs: 20000,
};

const state = {
  config: readRuntimeConfig(),
  moments: [],
  renderIndex: 0,
  revealObserver: null,
  sentinelObserver: null,
  timer: {
    baseTotalSeconds: null,
    baseNowMs: null,
    baseLocalMs: null,
    sinceIso: null,
    tickIntervalId: null,
    syncIntervalId: null,
    syncFailed: false,
  },
};

const elements = {
  root: document.getElementById("timeline-app"),
  timeline: document.getElementById("timeline"),
  status: document.getElementById("timeline-status"),
  sentinel: document.getElementById("timeline-sentinel"),
  countdown: document.getElementById("countdown"),
  countdownValue: document.getElementById("countdown-value"),
  countdownMeta: document.getElementById("countdown-meta"),
};

function readRuntimeConfig() {
  const injected = window.__TIMELINE_CONFIG__;
  if (!injected || typeof injected !== "object") {
    return { ...DEFAULT_CONFIG };
  }

  const merged = {
    ...DEFAULT_CONFIG,
    ...injected,
  };

  return {
    apiBaseUrl: String(merged.apiBaseUrl || "").trim(),
    cardsListPath: String(merged.cardsListPath || DEFAULT_CONFIG.cardsListPath).trim(),
    cardByIdPathTemplate: String(merged.cardByIdPathTemplate || DEFAULT_CONFIG.cardByIdPathTemplate).trim(),
    imagesPath: String(merged.imagesPath || DEFAULT_CONFIG.imagesPath).trim(),
    timerPath: String(merged.timerPath || DEFAULT_CONFIG.timerPath).trim(),
    requestTimeoutMs: Number(merged.requestTimeoutMs) > 0 ? Number(merged.requestTimeoutMs) : DEFAULT_CONFIG.requestTimeoutMs,
    cacheTtlMs: Number(merged.cacheTtlMs) > 0 ? Number(merged.cacheTtlMs) : DEFAULT_CONFIG.cacheTtlMs,
    maxMoments: Number(merged.maxMoments) > 0 ? Number(merged.maxMoments) : DEFAULT_CONFIG.maxMoments,
    batchSize: Number(merged.batchSize) > 0 ? Number(merged.batchSize) : DEFAULT_CONFIG.batchSize,
    maxRetries: Number(merged.maxRetries) > 0 ? Number(merged.maxRetries) : DEFAULT_CONFIG.maxRetries,
    timerSyncIntervalMs:
      Number(merged.timerSyncIntervalMs) > 0 ? Number(merged.timerSyncIntervalMs) : DEFAULT_CONFIG.timerSyncIntervalMs,
  };
}

function updateStatus(message) {
  if (elements.status) {
    elements.status.textContent = message;
  }
}

function cacheKey(config) {
  return ["timeline", config.apiBaseUrl || "same-origin", config.cardsListPath].join("::");
}

function readCachedRawMoments(config) {
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
    if (!Number.isFinite(savedAt) || Date.now() - savedAt > config.cacheTtlMs) {
      return null;
    }

    return Array.isArray(payload.moments) ? payload.moments : null;
  } catch (_error) {
    return null;
  }
}

function saveCachedRawMoments(config, moments) {
  try {
    sessionStorage.setItem(
      cacheKey(config),
      JSON.stringify({
        savedAt: Date.now(),
        moments,
      })
    );
  } catch (_error) {
    // Ignore cache write failures.
  }
}

async function fetchAllCards(apiConfig, maxMoments) {
  const allMoments = [];
  const seenCursors = new Set();
  let cursor = null;

  while (allMoments.length < maxMoments) {
    const payload = await getCardsList(apiConfig, cursor);
    const pageMoments = Array.isArray(payload?.moments) ? payload.moments : [];
    allMoments.push(...pageMoments);

    const nextCursor = typeof payload?.nextCursor === "string" && payload.nextCursor ? payload.nextCursor : null;
    if (!nextCursor || seenCursors.has(nextCursor)) {
      break;
    }

    seenCursors.add(nextCursor);
    cursor = nextCursor;
  }

  return allMoments.slice(0, maxMoments);
}

async function mapWithConcurrency(items, concurrency, mapper) {
  const result = new Array(items.length);
  let cursor = 0;

  async function worker() {
    while (cursor < items.length) {
      const current = cursor;
      cursor += 1;
      result[current] = await mapper(items[current]);
    }
  }

  const workerCount = Math.max(1, Math.min(concurrency, items.length));
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return result;
}

async function hydrateSummaries(rawMoments, apiConfig) {
  const summaryCount = rawMoments.filter((moment) => isSummaryMoment(moment)).length;
  if (summaryCount === 0) {
    return rawMoments;
  }

  updateStatus("Loading missing card details...");

  return mapWithConcurrency(rawMoments, 6, async (moment) => {
    if (!isSummaryMoment(moment)) {
      return moment;
    }

    const cardId = String(moment._id || "").trim();
    if (!cardId) {
      return moment;
    }

    try {
      return await getCardById(apiConfig, cardId);
    } catch (_error) {
      return moment;
    }
  });
}

function normalizeTimelineMoments(rawMoments) {
  const normalized = rawMoments
    .map((moment) => normalizeMoment(moment))
    .filter((moment) => moment !== null)
    .filter((moment) => moment.visibility !== "draft");

  return sortMomentsByDate(normalized);
}

function teardownObservers() {
  state.revealObserver?.disconnect();
  state.sentinelObserver?.disconnect();
  state.revealObserver = null;
  state.sentinelObserver = null;
}

function setupObservers() {
  teardownObservers();

  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
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
        threshold: 0.2,
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
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }

    const card = event.target.closest(".timeline-card");
    if (!card) {
      return;
    }

    const cards = [...elements.timeline.querySelectorAll(".timeline-card")];
    const currentIndex = cards.indexOf(card);
    if (currentIndex === -1) {
      return;
    }

    const nextIndex = event.key === "ArrowDown" ? currentIndex + 1 : currentIndex - 1;
    const nextCard = cards[nextIndex];
    if (!nextCard) {
      return;
    }

    event.preventDefault();
    nextCard.focus();
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

    return error.message || "Cards API request failed.";
  }

  if (error?.name === "AbortError") {
    return "Request timed out. Please retry.";
  }

  return "Failed to load timeline. Please retry.";
}

function resetTimeline() {
  clearContainer(elements.timeline);
  state.renderIndex = 0;
}

function updateSentinelVisibility() {
  if (!elements.sentinel) {
    return;
  }

  elements.sentinel.hidden = state.renderIndex >= state.moments.length;
}

function appendBatch() {
  if (state.renderIndex >= state.moments.length) {
    updateSentinelVisibility();
    return;
  }

  const fragment = document.createDocumentFragment();
  const batchSize = Math.max(1, state.config.batchSize);
  const end = Math.min(state.renderIndex + batchSize, state.moments.length);

  for (let index = state.renderIndex; index < end; index += 1) {
    const moment = state.moments[index];

    const imageUrls = moment.images.slice(0, 6).map((imageName) => {
      return buildImageUrl(state.config.apiBaseUrl, state.config.imagesPath, imageName);
    });

    fragment.append(
      createMomentCard({
        moment,
        index,
        imageUrls,
        revealObserver: state.revealObserver,
      })
    );
  }

  state.renderIndex = end;
  elements.timeline.append(fragment);
  updateSentinelVisibility();
}

function renderMoments(moments) {
  resetTimeline();
  state.moments = moments;

  if (moments.length === 0) {
    renderEmptyState(elements.timeline);
    updateStatus("Timeline is empty");
    updateSentinelVisibility();
    return;
  }

  appendBatch();
  updateStatus(`Timeline loaded: ${moments.length} moments`);
}

async function loadTimeline({ withLoading }) {
  if (withLoading) {
    renderLoadingState(elements.timeline);
    updateStatus("Loading timeline...");
  }

  const apiConfig = buildApiConfig(state.config);
  const rawCards = await fetchAllCards(apiConfig, state.config.maxMoments);
  const hydrated = await hydrateSummaries(rawCards, apiConfig);

  saveCachedRawMoments(state.config, hydrated);
  renderMoments(normalizeTimelineMoments(hydrated));
}

async function refresh({ withLoading }) {
  try {
    await loadTimeline({ withLoading });
  } catch (error) {
    if (state.moments.length > 0) {
      updateStatus(`Timeline refresh failed: ${formatErrorMessage(error)}`);
      return;
    }

    renderErrorState(elements.timeline, formatErrorMessage(error), () => {
      void refresh({ withLoading: true });
    });
    updateStatus("Timeline failed to load");
  }
}

function setTimerUi({ value, meta, tone = "normal" }) {
  if (!elements.countdown || !elements.countdownValue || !elements.countdownMeta) {
    return;
  }

  elements.countdown.dataset.tone = tone;
  elements.countdownValue.textContent = value;
  elements.countdownMeta.textContent = meta;
}

function renderElapsedTick() {
  if (state.timer.baseTotalSeconds === null || state.timer.baseLocalMs === null || state.timer.baseNowMs === null) {
    setTimerUi({
      value: state.timer.syncFailed ? "—" : "...",
      meta: state.timer.syncFailed ? "Timer API недоступен" : "Подключаем timer API",
      tone: state.timer.syncFailed ? "warning" : "loading",
    });
    return;
  }

  const deltaSeconds = Math.max(0, Math.floor((Date.now() - state.timer.baseLocalMs) / 1000));
  const estimatedNowMs = state.timer.baseNowMs + Date.now() - state.timer.baseLocalMs;
  const parts = calculateElapsedParts(state.timer.sinceIso, estimatedNowMs, state.timer.baseTotalSeconds + deltaSeconds);
  const value = formatElapsedValue(parts);

  const sinceLabel = formatSinceLabel(state.timer.sinceIso);
  let meta = sinceLabel ? `с ${sinceLabel} UTC` : "данные timer API";
  if (state.timer.syncFailed) {
    meta = `${meta} · локальный тик`;
  }

  setTimerUi({
    value,
    meta,
    tone: state.timer.syncFailed ? "warning" : "normal",
  });
}

async function syncTimer() {
  const apiConfig = buildApiConfig(state.config);

  try {
    const timerPayload = await getTimer(apiConfig);
    const parsed = parseTimerPayload(timerPayload, Date.now());

    if (parsed.totalSeconds === null) {
      throw new Error("timer payload missing elapsed values");
    }

    const serverLagSeconds = Math.max(0, Math.floor((Date.now() - parsed.baseNowMs) / 1000));

    state.timer.baseTotalSeconds = parsed.totalSeconds + serverLagSeconds;
    state.timer.baseNowMs = parsed.baseNowMs + serverLagSeconds * 1000;
    state.timer.baseLocalMs = Date.now();
    state.timer.sinceIso = parsed.sinceIso;
    state.timer.syncFailed = false;
  } catch (_error) {
    state.timer.syncFailed = true;
  }

  renderElapsedTick();
}

function startTimer() {
  state.timer.tickIntervalId && window.clearInterval(state.timer.tickIntervalId);
  state.timer.syncIntervalId && window.clearInterval(state.timer.syncIntervalId);

  renderElapsedTick();

  state.timer.tickIntervalId = window.setInterval(() => {
    renderElapsedTick();
  }, 1000);

  void syncTimer();

  const syncPeriod = Math.max(10000, state.config.timerSyncIntervalMs);
  state.timer.syncIntervalId = window.setInterval(() => {
    void syncTimer();
  }, syncPeriod);
}

async function bootstrap() {
  if (!elements.root || !elements.timeline) {
    return;
  }

  setupObservers();
  setupKeyboardNavigation();
  startTimer();

  const cachedRaw = readCachedRawMoments(state.config);
  if (cachedRaw) {
    renderMoments(normalizeTimelineMoments(cachedRaw));
    updateStatus("Loaded cached timeline, refreshing data...");
    void refresh({ withLoading: false });
    return;
  }

  await refresh({ withLoading: true });
}

void bootstrap();
