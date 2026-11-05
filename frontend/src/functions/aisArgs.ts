/** AIS: pure argument and text helpers (no DOM, no network; vitest runs them). */

/** The chokepoint presets the backend knows (`world/ais.py` PRESETS); a vitest keeps the two lists equal. */
export const AIS_AREAS = ["SUEZ", "PANAMA", "HORMUZ", "MALACCA", "BABEL", "BOSPHORUS", "GIBRALTAR", "DOVER"] as const;

/** How long one listen takes, in seconds: equals the backend's `world/ais.py` LISTEN_S (a pytest reads this file to keep them equal). */
export const AIS_LISTEN_S = 15;
/** How long the server remembers a ship's last position, in seconds: equals `providers/aisstream.py` POSITION_TTL_S (same pytest). */
export const AIS_MEMORY_S = 300;

/** The loading line, so the promised wait is the real one. */
export function listeningText(): string {
  return `LISTENING FOR ABOUT ${AIS_LISTEN_S} SECONDS…`;
}

/** The honest label for rows that did not come from this listen. Minutes come from the server's own limit when it sent one. */
export function memoryNote(memorySeconds: number = AIS_MEMORY_S): string {
  return `POSITIONS UP TO ${Math.round(memorySeconds / 60)} MIN OLD FROM EARLIER LISTENS ARE SHOWN DIMMED AND MARKED MEMORY (SEE THE AGE COLUMN); THE REST WERE HEARD IN THIS LISTEN`;
}

/** FROM column: LIVE = heard during this listen, MEMORY = remembered from an earlier one. */
export function fmtFrom(remembered: boolean): string {
  return remembered ? "MEMORY" : "LIVE";
}

/** `AIS SUEZ`, `AIS BOX 25.6 -80.2 25.8 -79.9`; with no words the first preset is shown. */
export function aisQuery(args: string[]): string {
  const q = args.filter(Boolean).join(" ").trim().toUpperCase();
  return q || AIS_AREAS[0];
}

/** The preset after (dir 1) or before (dir -1) the current one, wrapping round. From a custom BOX it starts at the first or last preset. */
export function stepArea(query: string, dir: 1 | -1): string {
  const i = (AIS_AREAS as readonly string[]).indexOf(query.toUpperCase());
  if (i < 0) return dir === 1 ? AIS_AREAS[0] : AIS_AREAS[AIS_AREAS.length - 1];
  return AIS_AREAS[(i + dir + AIS_AREAS.length) % AIS_AREAS.length];
}

/** Knots with one decimal; blank when the ship did not report a speed (never 0, which would claim "stopped"). */
export function fmtKnots(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : v.toFixed(1);
}

/** Whole degrees 0-359; blank when not reported. */
export function fmtDegrees(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : String(Math.round(v) % 360);
}

/** "30.210N 32.550E" for a table cell; the CSV keeps the plain numbers. */
export function fmtLatLon(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(3)}${lat < 0 ? "S" : "N"} ${Math.abs(lon).toFixed(3)}${lon < 0 ? "W" : "E"}`;
}

/** "ETA 11-12 06:00" is month-day hour:minute in UTC (AIS has no year). Blank when the ship gave none. */
export function fmtEta(eta: string | null | undefined): string {
  return eta ?? "";
}

/** Seconds as "45S", "3M", "2H" for an age column; blank when unknown. */
export function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, seconds);
  if (s < 90) return `${Math.round(s)}S`;
  if (s < 5400) return `${Math.round(s / 60)}M`;
  if (s < 129600) return `${Math.round(s / 3600)}H`;
  return `${Math.round(s / 86400)}D`;
}

/** What to say when a listen found no ships. It is NOT "there are no ships here": a few seconds on a beta feed proves little. */
export function quietText(listenedS: number, received: number): string {
  return `NO POSITION REPORTS IN ${listenedS.toFixed(0)} S (${received} MESSAGES): A QUIET AREA OR A SLOW FEED (THE FREE FEED HAS NO RECEIVERS IN SOME STRAITS, SUCH AS SUEZ OR HORMUZ). THIS DOES NOT SHOW THE AREA IS EMPTY. F5 LISTENS AGAIN`;
}
