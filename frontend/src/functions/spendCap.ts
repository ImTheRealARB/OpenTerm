/** APIKEYS spend line and cap input (pure, for vitest). The backend accepts US$0-1000 per day. */
export const MAX_CAP = 1000;

export interface Spend {
  today: number;
  cap: number;
}

/** "2", "2.5", "$2.50", "US$ 2" -> 2.5 etc. (cents); anything else, or outside 0..MAX_CAP -> null. */
export function parseCap(text: string): number | null {
  const m = /^\s*(?:US)?\$?\s*(\d+(?:\.\d*)?|\.\d+)\s*$/i.exec(text);
  if (!m) return null;
  const v = Math.round(Number(m[1]) * 100) / 100;
  return Number.isFinite(v) && v >= 0 && v <= MAX_CAP ? v : null;
}

export const spendLine = (s: Spend | undefined) =>
  s ? `AI SPEND TODAY US$${s.today.toFixed(2)} / ${s.cap.toFixed(2)} CAP` : "AI SPEND TODAY —";
