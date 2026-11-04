import type { A } from "./math";

/** Input columns. `t` (epoch seconds) is optional; only session VWAP uses it. */
export interface Cols {
  o: A;
  h: A;
  l: A;
  c: A;
  v: A;
  t?: A;
}

export type Category = "trend" | "momentum" | "volatility" | "volume" | "other";

export interface ParamDef {
  name: string;
  default: number;
  min: number;
  max: number;
}

export interface IndicatorDef {
  id: string;
  name: string;
  category: Category;
  /** "price" = drawn over the candles, "lower" = own pane. */
  pane: "price" | "lower";
  params: ParamDef[];
  outputs: string[];
  /** One beginner sentence. */
  plain: string;
  /** p holds the param values in `params` order. Returns one array per output. */
  fn: (c: Cols, p: number[]) => A[];
}

export const P = (name: string, def: number, min = 1, max = 500): ParamDef => ({ name, default: def, min, max });
