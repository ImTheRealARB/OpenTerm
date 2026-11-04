/** Pure helpers for "alert from the chart": round a clicked price to a sensible tick and pick the direction. */

/** Tick size by price magnitude (a click lands on a pixel, not on a tradable price). */
export function alertTick(price: number): number {
  const p = Math.abs(price);
  if (p < 0.1) return 0.0001;
  if (p < 1) return 0.001;
  if (p < 10) return 0.01;
  if (p < 1000) return 0.05;
  if (p < 10000) return 0.5;
  return 1;
}

/** Decimals used to write a rounded price. */
function alertDecimals(price: number): number {
  const t = alertTick(price);
  return t >= 1 ? 0 : t >= 0.01 ? 2 : t >= 0.001 ? 3 : 4;
}

/** Rounds to the tick; null when the price is not a positive finite number. */
export function roundAlertPrice(price: number): number | null {
  if (!Number.isFinite(price) || price <= 0) return null;
  const t = alertTick(price);
  const r = Math.round(price / t) * t;
  return r > 0 ? Number(r.toFixed(6)) : null;
}

/** The rounded price as text with a fixed number of decimals ("231.50"). */
export function fmtAlertPrice(price: number): string {
  return price.toFixed(alertDecimals(price));
}

/** Above the last price -> ">" (alert when it rises to it); below -> "<". Exactly at the last price -> ">". */
export function alertDirection(price: number, last: number): ">" | "<" {
  return price < last ? "<" : ">";
}
