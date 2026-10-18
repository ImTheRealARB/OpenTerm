/**
 * Phase 14: the OSA structure handed to `BT <SYM> MKT=options`. Pure (no window): OSA remembers what it shows,
 * BT reads it back. Nothing is defaulted here: a field OSA does not show (expiry typed as T=, open date, exercise
 * style) stays absent and the backend answers `NOT RUNNABLE: MISSING ...`.
 */
import { keyValueArgs } from "../research/tablePayload";

export interface OsaLeg {
  type: "call" | "put";
  strike: number;
  qty: number;
  expiry?: string;
}
export interface OsaStructure {
  legs: OsaLeg[];
  risk_free_rate?: number;
  contract_multiplier?: number;
}
export interface OsaShape {
  sections: { id: string; rows: Record<string, unknown>[] }[];
}

export const NO_OSA = "NOT RUNNABLE: NO OSA STRUCTURE (OPEN OSA FIRST: <SYM> OSA LEGS=... EXP=YYYY-MM-DD)";
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const store = new Map<string, OsaStructure>();

/** The structure an OSA payload shows, or null when it shows none. `args` are the OSA command arguments (for EXP=). */
export function osaStructure(data: OsaShape, args: string[]): OsaStructure | null {
  const legRows = data.sections.find((s) => s.id === "legs")?.rows ?? [];
  const exp = keyValueArgs(args).params.exp;
  const expiry = exp && DATE.test(exp) ? exp : undefined;
  const legs: OsaLeg[] = [];
  for (const r of legRows) {
    const t = String(r.type ?? "").toUpperCase();
    if ((t !== "C" && t !== "P") || typeof r.strike !== "number" || typeof r.qty !== "number") return null;
    legs.push({ type: t === "C" ? "call" : "put", strike: r.strike, qty: r.qty, ...(expiry ? { expiry } : {}) });
  }
  if (!legs.length) return null;
  const inputs = data.sections.find((s) => s.id === "inputs")?.rows ?? [];
  const input = (name: string) => inputs.find((r) => r.name === name);
  const out: OsaStructure = { legs };
  const rate = input("R")?.rate;
  if (typeof rate === "number") out.risk_free_rate = rate;
  const mult = Number(input("MULT")?.value);
  if (Number.isFinite(mult) && mult > 0) out.contract_multiplier = mult;
  return out;
}

export function rememberOsa(symbol: string, s: OsaStructure | null): void {
  if (s) store.set(symbol.toUpperCase(), s);
  else store.delete(symbol.toUpperCase());
}
export const lastOsa = (symbol: string): OsaStructure | undefined => store.get(symbol.toUpperCase());

export interface OptionsExtras {
  open?: string;
  close?: string;
  style?: string;
}

/** The `structure` object of POST /api/bt/run: only fields that are known (the backend lists what is missing). */
export function btStructure(s: OsaStructure, x: OptionsExtras) {
  return {
    legs: s.legs,
    ...(x.open ? { open_date: x.open } : {}),
    ...(x.close ? { close_date: x.close } : {}),
    ...(s.risk_free_rate !== undefined ? { risk_free_rate: s.risk_free_rate } : {}),
    ...(s.contract_multiplier !== undefined ? { contract_multiplier: s.contract_multiplier } : {}),
    ...(x.style ? { exercise_style: x.style } : {}),
  };
}
