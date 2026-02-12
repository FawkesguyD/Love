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

export function getNextValentineTargetUtcMs(referenceValue) {
  const referenceMs = toUtcMs(referenceValue) ?? Date.now();
  const referenceDate = new Date(referenceMs);
  const year = referenceDate.getUTCFullYear();

  const currentYearTarget = Date.UTC(year, 1, 14, 0, 0, 0, 0);
  if (referenceMs < currentYearTarget) {
    return currentYearTarget;
  }

  return Date.UTC(year + 1, 1, 14, 0, 0, 0, 0);
}

export function splitRemainingDuration(remainingMs) {
  const normalized = Math.max(0, Math.floor(Number(remainingMs) || 0));
  let seconds = Math.floor(normalized / 1000);

  const days = Math.floor(seconds / 86400);
  seconds -= days * 86400;

  const hours = Math.floor(seconds / 3600);
  seconds -= hours * 3600;

  const minutes = Math.floor(seconds / 60);
  seconds -= minutes * 60;

  return {
    days,
    hours,
    minutes,
    seconds,
    totalMs: normalized,
  };
}

export function formatCountdownValue(parts) {
  return `${parts.days}д ${parts.hours}ч ${parts.minutes}м ${parts.seconds}с`;
}

export function formatTargetDateLabel(targetMs, locale = "ru-RU") {
  const formatter = new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  return formatter.format(new Date(targetMs));
}
