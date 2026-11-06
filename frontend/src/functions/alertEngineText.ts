/**
 * Plain text for the ALRT panel about the SERVER alert engine (Phase 20). Pure, so a unit test can pin the wording.
 * The engine fires alerts while the OpenTerm backend runs, even with no browser open; this says so, how fresh its data is,
 * and every match it refused to act on (and why), because "my alert did not fire" is the question this panel must answer.
 */
import type { AlertEngineState } from "../net/types";

/** "3 s", "2 min", "1 h": how long ago, for ages in seconds. */
export function fmtAge(s: number): string {
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${Math.round(s / 3600)} h`;
}

export interface EngineView {
  /** CSS class for the headline: "up" running, "warn" fixture mode, "err" state unknown or stopped. */
  cls: "up" | "warn" | "err";
  /** One line: what the engine is and its honest limit. */
  head: string;
  /** Watching and data freshness. */
  detail: string;
  /** One line per refused match: "AAPL > 200: STALE TICK 300s OLD (4 min ago)". */
  skipped: string[];
}

export function engineView(s: AlertEngineState | null): EngineView {
  if (!s) return { cls: "err", head: "SERVER ALERT ENGINE: STATE UNKNOWN (BACKEND NOT ANSWERING)", detail: "", skipped: [] };
  if (!s.running) return { cls: "err", head: "SERVER ALERT ENGINE: STOPPED", detail: "", skipped: [] };
  const head = s.fixtures
    ? "SERVER ALERT ENGINE: FIXTURE MODE, IT FIRES NOTHING (THIS TAB FIRES ON THE RECORDED DATA)"
    : `SERVER ALERT ENGINE: ${s.note}`;
  const watching = s.watching.length ? `WATCHING ${s.watching.join(", ")}` : "NO PRICE ALERTS TO WATCH";
  const tick = s.last_tick_age_s == null ? "NO TICK YET" : `LAST TICK ${fmtAge(s.last_tick_age_s)} AGO`;
  const news = s.last_news_poll_age_s == null ? "NEWS NOT CHECKED YET" : `NEWS CHECKED ${fmtAge(s.last_news_poll_age_s)} AGO`;
  return {
    cls: s.fixtures ? "warn" : "up",
    head,
    detail: `${watching} · ${tick} · ${news}`,
    skipped: s.skipped.map((k) => `${k.label}: ${k.reason} (${fmtAge(k.age_s)} ago)`),
  };
}
