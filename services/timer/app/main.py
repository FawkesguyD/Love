#TODO: переписать логику чтобы сервис не дрочил балансер каждую секунду 

from datetime import datetime, timezone

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="Timer Service")

START_TIME = datetime(2025, 3, 6, 18, 0, 0, tzinfo=timezone.utc)
START_TIME_ISO = "2025-03-06T18:00:00.000Z"


def to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def add_years(value: datetime, years: int) -> datetime:
    target_year = value.year + years
    try:
        return value.replace(year=target_year)
    except ValueError:
        return value.replace(year=target_year, day=28)


def calculate_elapsed(now: datetime) -> tuple[dict[str, int], int]:
    years = 0
    while add_years(START_TIME, years + 1) <= now:
        years += 1

    anchor = add_years(START_TIME, years)
    remainder = now - anchor
    remainder_seconds = remainder.seconds

    elapsed = {
        "years": years,
        "days": remainder.days,
        "hours": remainder_seconds // 3600,
        "minutes": (remainder_seconds % 3600) // 60,
        "seconds": remainder_seconds % 60,
    }

    total_seconds = int((now - START_TIME).total_seconds())
    return elapsed, total_seconds


def normalize_theme(value: str | None) -> str:
    if value is None:
        return "light"

    normalized = value.strip().lower()
    if normalized == "dark":
        return "dark"
    return "light"


def build_view_html(theme: str) -> str:
    return """<!doctype html>
<html lang="en" data-theme="__THEME__">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Timer</title>
    <style>
      :root {
        --bg: #f7f8fa;
        --fg: #14171a;
        --muted: #5f6670;
        --error: #b00020;
      }

      html[data-theme="dark"] {
        --bg: #111319;
        --fg: #f1f4f8;
        --muted: #a7afba;
        --error: #ff7f96;
      }

      html, body {
        width: 100%;
        height: 100%;
        margin: 0;
      }

      body {
        background: var(--bg);
        color: var(--fg);
        font-family: monospace;
      }

      .viewport {
        width: 100vw;
        height: 100vh;
        box-sizing: border-box;
        padding: 20vh 20vw;
      }

      .timer {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
        text-align: center;
      }

      h1 {
        margin: 0 0 12px;
        font-size: clamp(20px, 2.5vw, 34px);
      }

      .meta {
        margin: 0;
        color: var(--muted);
        font-size: clamp(11px, 1.2vw, 16px);
      }

      .clock {
        margin: 18px 0 14px;
        font-size: clamp(24px, 5vw, 64px);
        line-height: 1.2;
      }

      .error {
        margin: 10px 0 0;
        color: var(--error);
        font-size: clamp(12px, 1.3vw, 16px);
      }
    </style>
  </head>
  <body>
    <main class="viewport">
      <section class="timer">
        <h1>Timer</h1>
        <p class="meta">This timer will never stop</p>
        <p class="clock" id="elapsed">-</p>
        <p class="error" id="error"></p>
      </section>
    </main>
    <script>
      async function refresh() {
        const errorNode = document.getElementById("error");
        try {
          const response = await fetch("/api/timer");
          if (!response.ok) {
            throw new Error("bad response");
          }
          const payload = await response.json();
          const e = payload.elapsed;
          document.getElementById("elapsed").textContent =
            `${e.years}y ${e.days}d ${e.hours}h ${e.minutes}m ${e.seconds}s`;
          errorNode.textContent = "";
        } catch (_err) {
          errorNode.textContent = "error loading time";
        }
      }

      refresh();
      setInterval(refresh, 1000);
    </script>
  </body>
</html>
""".replace("__THEME__", theme)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/time")
def get_time() -> dict:
    now = datetime.now(timezone.utc)
    elapsed, total_seconds = calculate_elapsed(now)

    return {
        "since": START_TIME_ISO,
        "now": to_iso_utc(now),
        "elapsed": elapsed,
        "totalSeconds": total_seconds,
    }


@app.get("/view", response_class=HTMLResponse)
def view(theme: str | None = Query(default=None)) -> HTMLResponse:
    resolved_theme = normalize_theme(theme)
    return HTMLResponse(content=build_view_html(resolved_theme))
