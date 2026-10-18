/** Loads exchange holidays for the market lights from /api/world/holidays (NY by rule; LN, TK, HK from Nager.Date; IN has no source). Failures are silent: the lights fall back to weekday sessions and say so. */
import { worldApi } from "../net/api";
import { MARKETS, hasClosures, setClosures } from "./hours";

const tried = new Set<string>();
export const unavailable = new Set<string>();

export async function loadHolidays(now = new Date()): Promise<void> {
  const years = [now.getUTCFullYear()];
  if (now.getUTCMonth() === 11) years.push(now.getUTCFullYear() + 1);
  await Promise.all(
    MARKETS.flatMap((m) =>
      years.map(async (year) => {
        const k = `${m.code}:${year}`;
        if (tried.has(k) || hasClosures(m.code, year)) return;
        tried.add(k);
        try {
          const env = await worldApi.holidays(m.code, year);
          const d = env.data;
          setClosures(m.code, year, d.holidays.filter((h) => h.national).map((h) => h.date), d.early.map((h) => h.date), d.basis);
          unavailable.delete(m.code);
        } catch {
          unavailable.add(m.code);
        }
      }),
    ),
  );
}
