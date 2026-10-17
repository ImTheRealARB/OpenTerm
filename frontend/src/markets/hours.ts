/**
 * Regular-session market hours. Weekends are closed; exchange holidays are NOT modelled yet
 * (see docs/DATA_LIMITS.md), so a light can show OPEN on a holiday.
 */
export interface Market {
  code: string;
  tz: string;
  /** Sessions as [startMinute, endMinute] in exchange local time. */
  sessions: [number, number][];
}

const hm = (h: number, m = 0) => h * 60 + m;

export const MARKETS: Market[] = [
  { code: "NY", tz: "America/New_York", sessions: [[hm(9, 30), hm(16)]] },
  { code: "LN", tz: "Europe/London", sessions: [[hm(8), hm(16, 30)]] },
  { code: "IN", tz: "Asia/Kolkata", sessions: [[hm(9, 15), hm(15, 30)]] },
  { code: "TK", tz: "Asia/Tokyo", sessions: [[hm(9), hm(11, 30)], [hm(12, 30), hm(15, 30)]] },
  { code: "HK", tz: "Asia/Hong_Kong", sessions: [[hm(9, 30), hm(12)], [hm(13), hm(16)]] },
];

const fmtCache = new Map<string, Intl.DateTimeFormat>();
function fmt(tz: string): Intl.DateTimeFormat {
  let f = fmtCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    fmtCache.set(tz, f);
  }
  return f;
}

export function isOpen(m: Market, now: Date): boolean {
  let wd = "";
  let h = 0;
  let min = 0;
  for (const p of fmt(m.tz).formatToParts(now)) {
    if (p.type === "weekday") wd = p.value;
    else if (p.type === "hour") h = Number(p.value);
    else if (p.type === "minute") min = Number(p.value);
  }
  if (wd === "Sat" || wd === "Sun") return false;
  const t = h * 60 + min;
  return m.sessions.some(([a, b]) => t >= a && t < b);
}
