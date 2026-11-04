/** The indicator catalog: ~100 entries, each pure over Float64Array columns. Load via dynamic import (never in the startup bundle). */
import { MOMENTUM, VOLATILITY, VOLUME } from "./momentum";
import { TREND } from "./trend";
import type { A } from "./math";
import type { Cols, IndicatorDef } from "./types";

export type { Cols, IndicatorDef, ParamDef, Category } from "./types";

export const CATALOG: IndicatorDef[] = [...TREND, ...MOMENTUM, ...VOLATILITY, ...VOLUME];

const BY_ID = new Map(CATALOG.map((d) => [d.id, d]));
export const findIndicator = (id: string): IndicatorDef | undefined => BY_ID.get(id.toUpperCase());

/** Param values for an indicator: given values (clamped to the declared range) or defaults. */
export function resolveParams(def: IndicatorDef, given?: number[]): number[] {
  return def.params.map((p, i) => {
    const v = given?.[i];
    return typeof v === "number" && Number.isFinite(v) ? Math.min(p.max, Math.max(p.min, v)) : p.default;
  });
}

export function runIndicator(id: string, cols: Cols, params?: number[]): A[] | null {
  const def = findIndicator(id);
  return def ? def.fn(cols, resolveParams(def, params)) : null;
}
