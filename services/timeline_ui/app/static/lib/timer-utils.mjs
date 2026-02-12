function toFiniteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toSafeUtcDate(value) {
  const timestamp = toUtcMs(value);
  if (timestamp === null) {
    return null;
  }

  return new Date(timestamp);
}

function toUtcMs(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  const date = new Date(value);
  const timestamp = date.getTime();
  if (Number.isNaN(timestamp)) {
    return null;
  }

  return timestamp;
}

export function splitElapsedDuration(totalSecondsValue) {
  const totalSeconds = Math.max(0, Math.floor(toFiniteNumber(totalSecondsValue) || 0));
  let rest = totalSeconds;

  const days = Math.floor(rest / 86400);
  rest -= days * 86400;

  const hours = Math.floor(rest / 3600);
  rest -= hours * 3600;

  const minutes = Math.floor(rest / 60);
  rest -= minutes * 60;

  const seconds = rest;

  return {
    days,
    hours,
    minutes,
    seconds,
    totalSeconds,
  };
}

function addYears(value, years) {
  const source = toSafeUtcDate(value);
  if (source === null) {
    return null;
  }

  const targetYear = source.getUTCFullYear() + years;
  const month = source.getUTCMonth();
  const day = source.getUTCDate();
  const hour = source.getUTCHours();
  const minute = source.getUTCMinutes();
  const second = source.getUTCSeconds();
  const millisecond = source.getUTCMilliseconds();

  const candidate = new Date(Date.UTC(targetYear, month, day, hour, minute, second, millisecond));
  if (candidate.getUTCMonth() === month && candidate.getUTCDate() === day) {
    return candidate;
  }

  return new Date(Date.UTC(targetYear, month, 28, hour, minute, second, millisecond));
}

export function calculateElapsedParts(sinceIso, nowValue, fallbackTotalSeconds = null) {
  const sinceDate = toSafeUtcDate(sinceIso);
  const nowDate = toSafeUtcDate(nowValue) || new Date();

  if (sinceDate === null) {
    const fallback = splitElapsedDuration(fallbackTotalSeconds || 0);
    return {
      years: 0,
      ...fallback,
    };
  }

  const nowMs = nowDate.getTime();
  const sinceMs = sinceDate.getTime();
  if (nowMs <= sinceMs) {
    return {
      years: 0,
      days: 0,
      hours: 0,
      minutes: 0,
      seconds: 0,
      totalSeconds: 0,
    };
  }

  let years = 0;
  while (true) {
    const nextAnchor = addYears(sinceDate, years + 1);
    if (nextAnchor === null || nextAnchor.getTime() > nowMs) {
      break;
    }
    years += 1;
  }

  const anchor = addYears(sinceDate, years);
  const anchorMs = anchor === null ? sinceMs : anchor.getTime();
  const remainder = splitElapsedDuration(Math.floor((nowMs - anchorMs) / 1000));

  return {
    years,
    days: remainder.days,
    hours: remainder.hours,
    minutes: remainder.minutes,
    seconds: remainder.seconds,
    totalSeconds: Math.floor((nowMs - sinceMs) / 1000),
  };
}

export function formatElapsedValue(parts) {
  const years = Math.max(0, Math.floor(toFiniteNumber(parts?.years) || 0));
  const yearLabel = years > 0 ? `${years}г ` : "";
  return `${yearLabel}${parts.days}д ${parts.hours}ч ${parts.minutes}м ${parts.seconds}с`;
}

export function formatSinceLabel(sinceIso, locale = "ru-RU") {
  const sinceMs = toUtcMs(sinceIso);
  if (sinceMs === null) {
    return "";
  }

  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(new Date(sinceMs));
}

function elapsedFromParts(payload) {
  const elapsed = payload?.elapsed;
  if (!elapsed || typeof elapsed !== "object") {
    return null;
  }

  const years = Math.max(0, Math.floor(toFiniteNumber(elapsed.years) || 0));
  const days = Math.max(0, Math.floor(toFiniteNumber(elapsed.days) || 0));
  const hours = Math.max(0, Math.floor(toFiniteNumber(elapsed.hours) || 0));
  const minutes = Math.max(0, Math.floor(toFiniteNumber(elapsed.minutes) || 0));
  const seconds = Math.max(0, Math.floor(toFiniteNumber(elapsed.seconds) || 0));

  return years * 365 * 86400 + days * 86400 + hours * 3600 + minutes * 60 + seconds;
}

export function parseTimerPayload(payload, clientNowMs = Date.now()) {
  const safeClientNowMs = toUtcMs(clientNowMs) || Date.now();
  const serverNowMs = toUtcMs(payload?.now);
  const sinceIso = typeof payload?.since === "string" ? payload.since : null;

  const fromTotalSeconds = toFiniteNumber(payload?.totalSeconds);
  if (fromTotalSeconds !== null && fromTotalSeconds >= 0) {
    return {
      totalSeconds: Math.floor(fromTotalSeconds),
      baseNowMs: serverNowMs || safeClientNowMs,
      sinceIso,
    };
  }

  const fromParts = elapsedFromParts(payload);
  if (fromParts !== null) {
    return {
      totalSeconds: fromParts,
      baseNowMs: serverNowMs || safeClientNowMs,
      sinceIso,
    };
  }

  const sinceMs = toUtcMs(sinceIso);
  if (sinceMs !== null) {
    const anchorNowMs = serverNowMs || safeClientNowMs;
    return {
      totalSeconds: Math.max(0, Math.floor((anchorNowMs - sinceMs) / 1000)),
      baseNowMs: anchorNowMs,
      sinceIso,
    };
  }

  return {
    totalSeconds: null,
    baseNowMs: serverNowMs || safeClientNowMs,
    sinceIso: null,
  };
}
