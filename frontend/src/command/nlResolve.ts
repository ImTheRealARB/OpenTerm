/**
 * Lazy half of nlRun.ts: loads natural.ts and the company list on first use and interprets typed text.
 */
import { isFunction } from "../functions/registry";
import type { UniverseEntry } from "../gui/companySearch";
import { known, split, type NlOutcome } from "./nlRun";

let universe: UniverseEntry[] | null = null;

async function load(): Promise<UniverseEntry[]> {
  if (universe) return universe;
  const m = await import("../gui/suggestData");
  const uni = await m.loadUniverse();
  if (!uni.length) return uni; // a failed load is not remembered (suggestData retries next time)
  known.symbols = new Set(uni.map((e) => e.symbol));
  return (universe = uni);
}

/** Interprets typed text. `asis`: run it exactly as typed (a real ticker, or nothing understood for a single word). */
export async function resolveNatural(input: string): Promise<NlOutcome> {
  const { prefix, body } = split(input);
  const [uni, nat] = await Promise.all([load(), import("./natural")]);
  const single = !/\s/.test(body);
  if (single && known.symbols?.has(body.toUpperCase())) return { kind: "asis" };
  const r = nat.interpretNatural(body, { isFunction, companies: uni.length ? uni : null });
  if (r.kind === "command") return { ...r, command: prefix + r.command };
  if (r.kind === "choices") return { kind: "choices", choices: r.choices.map((c) => ({ ...c, command: prefix + c.command })) };
  return single ? { kind: "asis" } : r;
}
