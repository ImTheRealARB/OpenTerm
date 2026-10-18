/**
 * Phase 14: `RATES` arguments -> the matching API view. Pure (no window), unit-tested.
 * No argument is the US Treasury panel (RATES.tsx); an argument picks a table: `EUR|GBP|CAD|JPY`, `SPRD`, `AUCT` or `NS <ccy>`.
 */
export const RATES_CURRENCIES = ["EUR", "GBP", "CAD", "JPY"] as const;
export const RATES_USAGE = "USAGE: RATES [EUR|GBP|CAD|JPY|SPRD|AUCT|NS <EUR|GBP|CAD|JPY>]";

export type RatesViewName = "curve" | "spreads" | "auctions";
export interface RatesView {
  view: RatesViewName;
  params: Record<string, string>;
}

const isCcy = (a: string) => (RATES_CURRENCIES as readonly string[]).includes(a);

/** null = not a recognised form (the panel shows usage instead of loading). Case does not matter; `EUR NS` works like `NS EUR`. */
export function ratesView(args: string[]): RatesView | null {
  const a = args.map((x) => x.trim().toUpperCase()).filter(Boolean);
  if (a.length === 1) {
    if (isCcy(a[0])) return { view: "curve", params: { ccy: a[0] } };
    if (a[0] === "SPRD" || a[0] === "SPREADS") return { view: "spreads", params: {} };
    if (a[0] === "AUCT" || a[0] === "AUCTIONS") return { view: "auctions", params: {} };
  }
  if (a.length === 2) {
    const ccy = a.find(isCcy);
    if (ccy && a.includes("NS")) return { view: "curve", params: { ccy, fit: "NS" } };
  }
  return null;
}
