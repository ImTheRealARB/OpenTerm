/**
 * Regular-session market hours plus exchange holidays. Weekends are closed. A holiday (`HOL`) closes the market all day; an early-close
 * day (`EARLY`, NYSE only: 13:00 ET) shortens it. Holiday data arrives from `/api/world/holidays` (markets/holidays.ts) and is optional:
 * until it loads (or when a market has no source, e.g. India) the lights follow weekday sessions only, and the tooltip says so.
 */
export interface Market {
  code: string;
  tz: string;
  /** Sessions as [startMinute, endMinute] in exchange local time. */
  sessions: [number, number][];
}

const hm = (h: number, m = 0) => h * 60 + m;
export const EARLY_CLOSE_MIN = hm(13);

export const MARKETS: Market[] = [
  { code: "NY", tz: "America/New_York", sessions: [[hm(9, 30), hm(16)]] },
  { code: "LN", tz: "Europe/London", sessions: [[hm(8), hm(16, 30)]] },
  { code: "IN", tz: "Asia/Kolkata", sessions: [[hm(9, 15), hm(15, 30)]] },
  { code: "TK", tz: "Asia/Tokyo", sessions: [[hm(9), hm(11, 30)], [hm(12, 30), hm(15, 30)]] },
  { code: "HK", tz: "Asia/Hong_Kong", sessions: [[hm(9, 30), hm(12)], [hm(13), hm(16)]] },
];

/** Where the closure dates came from. "fixed" = a partial rule (NSE: fixed-date holidays + Good Friday, festival holidays NOT included). */
export type Basis = "rules" | "public" | "fixed";

/** Tooltip text for a basis. "fixed" must say the list is incomplete: on a festival day the light still shows OPEN. */
export function basisNote(basis: Basis): string {
  if (basis === "rules") return "HOLIDAYS BY NYSE RULE";
  if (basis === "fixed") return "FIXED-DATE HOLIDAYS + GOOD FRIDAY ONLY: FESTIVAL HOLIDAYS (DIWALI, HOLI, EID...) NOT INCLUDED";
  return "PUBLIC HOLIDAYS (EXCHANGE MAY DIFFER)";
}
interface Closures {
  holidays: Set<string>;
  early: Set<string>;
  basis: Basis;
}
const closures = new Map<string, Closures>();
const key = (code: string, year: number) => `${code}:${year}`;

/** Registers the holiday and early-close dates (YYYY-MM-DD) of one market and year. */
export function setClosures(code: string, year: number, holidays: string[], early: string[], basis: Basis): void {
  closures.set(key(code, year), { holidays: new Set(holidays), early: new Set(early), basis });
}
export const hasClosures = (code: string, year: number) => closures.has(key(code, year));
export function clearClosures(): void {
  closures.clear();
}

const fmtCache = new Map<string, Intl.DateTimeFormat>();
function fmt(tz: string): Intl.DateTimeFormat {
  let f = fmtCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    fmtCache.set(tz, f);
  }
  return f;
}

interface Local {
  wd: string;
  ymd: string;
  year: number;
  minute: number;
}
function local(m: Market, now: Date): Local {
  let wd = "", y = "", mo = "", d = "";
  let h = 0, min = 0;
  for (const p of fmt(m.tz).formatToParts(now)) {
    if (p.type === "weekday") wd = p.value;
    else if (p.type === "year") y = p.value;
    else if (p.type === "month") mo = p.value;
    else if (p.type === "day") d = p.value;
    else if (p.type === "hour") h = Number(p.value);
    else if (p.type === "minute") min = Number(p.value);
  }
  return { wd, ymd: `${y}-${mo}-${d}`, year: Number(y), minute: h * 60 + min };
}

export type DayKind = "HOL" | "EARLY" | null;

function kindOf(m: Market, l: Local): DayKind {
  const c = closures.get(key(m.code, l.year));
  if (!c) return null;
  if (c.holidays.has(l.ymd)) return "HOL";
  return c.early.has(l.ymd) ? "EARLY" : null;
}

/** `HOL` on an exchange holiday, `EARLY` on an early-close day, else null (also null when no holiday data is loaded for the year). */
export function dayKind(m: Market, now: Date): DayKind {
  return kindOf(m, local(m, now));
}

/** True when `now` falls on a loaded holiday of the market (so `closed(m, now)` is false for an unloaded year: nothing is guessed). */
export const closed = (m: Market, now: Date) => dayKind(m, now) === "HOL";

/** Where the loaded holiday dates of `now`'s year come from, or null when none are loaded. */
export function basisOf(m: Market, now: Date): Basis | null {
  return closures.get(key(m.code, local(m, now).year))?.basis ?? null;
}

export function isOpen(m: Market, now: Date): boolean {
  const l = local(m, now);
  if (l.wd === "Sat" || l.wd === "Sun") return false;
  const kind = kindOf(m, l);
  if (kind === "HOL") return false;
  return m.sessions.some(([a, b]) => l.minute >= a && l.minute < (kind === "EARLY" ? Math.min(b, EARLY_CLOSE_MIN) : b));
}

export type Light = "open" | "closed" | "hol" | "early";
/** The light for the top bar: a holiday shows `hol` (HOL), an early-close day while open `early` (EARLY). */
export function lightOf(m: Market, now: Date): Light {
  const kind = dayKind(m, now);
  if (kind === "HOL" && ![ "Sat", "Sun" ].includes(local(m, now).wd)) return "hol";
  if (!isOpen(m, now)) return "closed";
  return kind === "EARLY" ? "early" : "open";
}
