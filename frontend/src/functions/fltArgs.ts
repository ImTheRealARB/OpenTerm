/** FLT: pure argument and text helpers (no DOM, no network; vitest runs them). The panel is FLT.tsx. */

/** The city presets the backend knows (`world/flights.py` PRESETS); a pytest reads this file to keep the two lists equal. */
export const FLT_AREAS = ["LONDON", "NYC", "DUBAI", "SINGAPORE", "MUMBAI", "BENGALURU", "FRANKFURT"] as const;

export const FLT_USAGE = "FLT <" + FLT_AREAS.join("|") + "> OR FLT BOX <SOUTH> <WEST> <NORTH> <EAST> OR FLT CALLSIGN <PREFIX>";

/** `FLT LONDON`, `FLT BOX 51 -1 52 1`, `FLT CALLSIGN BAW`; with no words the first preset is shown. */
export function fltQuery(args: string[]): string {
  const q = args.filter(Boolean).join(" ").trim().toUpperCase();
  return q || FLT_AREAS[0];
}

/** The preset after (dir 1) or before (dir -1) the current one, wrapping round. From a BOX or CALLSIGN it starts at the first or last preset. */
export function stepArea(query: string, dir: 1 | -1): string {
  const i = (FLT_AREAS as readonly string[]).indexOf(query.toUpperCase());
  if (i < 0) return dir === 1 ? FLT_AREAS[0] : FLT_AREAS[FLT_AREAS.length - 1];
  return FLT_AREAS[(i + dir + FLT_AREAS.length) % FLT_AREAS.length];
}

/** Whole feet with a thousands separator; blank when the aircraft did not report an altitude (never 0, which would claim "at sea level"). */
export function fmtFeet(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : v.toLocaleString("en-US");
}

/** Whole knots; blank when not reported. */
export function fmtKt(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : String(v);
}

/** Heading as three digits ("095") like a pilot reads it; blank when not reported. */
export function fmtHeading(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : String(v).padStart(3, "0");
}

/** Climb or descent in feet per minute with a sign: "+1,200", "-800"; blank when not reported, "0" when level. */
export function fmtVrate(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "";
  return (v > 0 ? "+" : "") + v.toLocaleString("en-US");
}

/** "30.210N 32.550E" for a table cell; the CSV keeps the plain numbers. */
export function fmtLatLon(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(3)}${lat < 0 ? "S" : "N"} ${Math.abs(lon).toFixed(3)}${lon < 0 ? "W" : "E"}`;
}

/** Seconds as "45S", "3M", "2H" for the position-age column; blank when unknown. */
export function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, seconds);
  if (s < 90) return `${Math.round(s)}S`;
  if (s < 5400) return `${Math.round(s / 60)}M`;
  return `${Math.round(s / 3600)}H`;
}

/** The credits line: what this call cost and what OpenSky says is left. A missing header is said, not guessed. */
export function creditsText(cost: number, remaining: number | null): string {
  const left = remaining == null ? "REMAINING CREDITS NOT REPORTED" : `${remaining.toLocaleString("en-US")} CREDITS LEFT`;
  return `THIS CALL COST ${cost} CREDIT${cost === 1 ? "" : "S"} · ${left}`;
}

/** What to say when no aircraft came back. It is NOT "the sky is empty": coverage is partial. */
export function quietText(received: number): string {
  return received > 0
    ? `${received} AIRCRAFT WERE HEARD BUT NONE HAS A POSITION YET`
    : "NO AIRCRAFT REPORTED HERE. THAT DOES NOT MEAN THE SKY IS EMPTY: OPENSKY RECEIVERS ARE VOLUNTEERS AND COVERAGE IS PARTIAL. F5 TRIES AGAIN";
}
