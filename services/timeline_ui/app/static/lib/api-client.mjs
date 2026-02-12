export class HttpError extends Error {
  constructor(status, payload) {
    const message = payload?.error?.message || payload?.detail || `HTTP ${status}`;
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.payload = payload;
  }
}

function normalizePath(path) {
  if (typeof path !== "string") {
    return "";
  }

  const trimmed = path.trim();
  if (!trimmed) {
    return "";
  }

  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    return trimmed;
  }

  return `/${trimmed.replace(/^\/+/, "")}`;
}

function replaceCardId(pathTemplate, cardId) {
  const safeId = encodeURIComponent(cardId);
  if (pathTemplate.includes("{id}")) {
    return pathTemplate.replace("{id}", safeId);
  }

  const trimmed = pathTemplate.replace(/\/+$/, "");
  return `${trimmed}/${safeId}`;
}

function buildUrl(apiBaseUrl, path, params = null) {
  const normalizedPath = normalizePath(path);
  if (!normalizedPath) {
    throw new Error("Empty API path");
  }

  const value = normalizedPath.startsWith("http") ? normalizedPath : `${String(apiBaseUrl || "").trim().replace(/\/+$/, "")}${normalizedPath}`;
  const url = new URL(value, window.location.origin);

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

async function fetchJson(url, { timeoutMs, retries }) {
  let lastError = null;

  for (let attempt = 1; attempt <= retries; attempt += 1) {
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
      } catch (_error) {
        payload = null;
      }

      if (!response.ok) {
        throw new HttpError(response.status, payload);
      }

      return payload;
    } catch (error) {
      lastError = error;

      const retryableNetworkError = error?.name === "AbortError" || error instanceof TypeError;
      const retryableHttpError = error instanceof HttpError && error.status >= 500;
      const canRetry = attempt < retries && (retryableNetworkError || retryableHttpError);

      if (!canRetry) {
        throw error;
      }
    } finally {
      window.clearTimeout(timer);
    }
  }

  throw lastError || new Error("Request failed");
}

function uniqueStrings(values) {
  return [...new Set(values.filter((value) => typeof value === "string" && value.trim()))];
}

export function buildApiConfig(config) {
  const retries = Number(config.maxRetries);

  return {
    apiBaseUrl: String(config.apiBaseUrl || "").trim().replace(/\/+$/, ""),
    cardsListPaths: uniqueStrings([config.cardsListPath, "/api/v1/cards"]),
    cardByIdPathTemplates: uniqueStrings([config.cardByIdPathTemplate, "/api/v1/cards/{id}"]),
    requestTimeoutMs: Number(config.requestTimeoutMs) > 0 ? Number(config.requestTimeoutMs) : 6000,
    maxRetries: Number.isFinite(retries) && retries > 0 ? retries : 2,
  };
}

export async function getCardsList(config, cursor = null) {
  let lastError = null;

  for (const listPath of config.cardsListPaths) {
    const url = buildUrl(config.apiBaseUrl, listPath, {
      limit: 100,
      order: "asc",
      cursor,
    });

    try {
      return await fetchJson(url.toString(), {
        timeoutMs: config.requestTimeoutMs,
        retries: config.maxRetries,
      });
    } catch (error) {
      lastError = error;
      if (error instanceof HttpError && error.status === 404) {
        continue;
      }
      throw error;
    }
  }

  throw lastError || new Error("Cards list endpoint is unavailable");
}

export async function getCardById(config, cardId) {
  let lastError = null;

  for (const template of config.cardByIdPathTemplates) {
    const path = replaceCardId(template, cardId);
    const url = buildUrl(config.apiBaseUrl, path);

    try {
      return await fetchJson(url.toString(), {
        timeoutMs: config.requestTimeoutMs,
        retries: config.maxRetries,
      });
    } catch (error) {
      lastError = error;
      if (error instanceof HttpError && error.status === 404) {
        continue;
      }
      throw error;
    }
  }

  throw lastError || new Error("Card details endpoint is unavailable");
}
