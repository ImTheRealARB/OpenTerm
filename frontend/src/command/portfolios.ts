/** Portfolios (`PORT`): stored in SQLite by the backend. Actions report through the status line. */
import type { ApiError } from "../net/core";
import { portfolioApi } from "../net/portfolioApi";
import type { PortfolioInfo, PositionIn } from "../net/types";
import { createStore } from "../state/store";
import type { SecurityRef } from "./markets";
import { parsePort } from "./portfolioArgs";
import { fail, info, statusMsg } from "./status";
import { errMessage } from "../net/errText";

export { parsePort, type PortAction } from "./portfolioArgs";

/** Saved portfolio names for autocomplete and the PORT index. null until first fetched. */
export const portfolioList = createStore<PortfolioInfo[] | null>(null);
/** Bumped after every change so open PORT panels refetch. */
export const portfolioVersion = createStore(0);

export async function refreshPortfolios(): Promise<PortfolioInfo[]> {
  const { portfolios } = await portfolioApi.portfolios();
  portfolioList.set(() => portfolios);
  return portfolios;
}


function changed(): void {
  portfolioVersion.set((n) => n + 1);
  void refreshPortfolios().catch(() => {});
}

async function run(what: string, call: () => Promise<unknown>, ok: string): Promise<boolean> {
  try {
    await call();
  } catch (e) {
    changed();
    return fail(`${what}: ${errMessage(e)}`);
  }
  info(ok);
  changed();
  return true;
}

const fmtQty = (n: number) => String(Math.round(n * 1e6) / 1e6);

export const addPosition = (name: string, p: PositionIn) =>
  run(`PORT ${name} NOT CHANGED`, () => portfolioApi.editPortfolio(name, { add: [p] }),
    `PORT ${name}: ${p.qty > 0 ? "ADDED" : "SOLD"} ${fmtQty(Math.abs(p.qty))} ${p.symbol}${p.cost != null ? ` @ ${p.cost}` : ""}`);

export const removePositions = (name: string, symbols: string[], note?: string) =>
  run(`PORT ${name} NOT CHANGED`, () => portfolioApi.editPortfolio(name, { remove: symbols }), note ?? `REMOVED ${symbols.join(" ")} FROM ${name}`);

export const setBase = (name: string, base: string) =>
  run(`PORT ${name} NOT CHANGED`, () => portfolioApi.editPortfolio(name, { base }), `PORT ${name}: BASE CURRENCY ${base}`);

/** Import: MERGE upserts the imported symbols, REPLACE swaps every position. */
export const importInto = (name: string, positions: PositionIn[], mode: "merge" | "replace") =>
  run(`PORT ${name} IMPORT FAILED`,
    () => (mode === "replace" ? portfolioApi.putPortfolio(name, positions) : portfolioApi.editPortfolio(name, { set: positions })),
    `PORT ${name}: IMPORTED ${positions.length} ROWS (${mode.toUpperCase()})`);

/** Undo of a removal restores the exact list. */
export const restorePortfolio = (name: string, positions: PositionIn[]) =>
  run(`PORT ${name} NOT RESTORED`, () => portfolioApi.putPortfolio(name, positions), `PORT ${name}: RESTORED`);

export async function deletePortfolio(name: string): Promise<boolean> {
  try {
    await portfolioApi.deletePortfolio(name);
  } catch (e) {
    return fail((e as ApiError).status === 404 ? `NO PORTFOLIO ${name}` : `PORT ${name} NOT DELETED: ${errMessage(e)}`);
  }
  info(`PORTFOLIO ${name} DELETED`);
  changed();
  return true;
}

// EXPORT / IMPORT typed on the command line are performed by the PORT panel once it shows that portfolio.
export const portfolioRequest = createStore<{ name: string; action: "export" | "import"; seq: number } | null>(null);
let handled = 0;

export function takeRequest(name: string): "export" | "import" | null {
  const r = portfolioRequest.get();
  if (!r || r.seq <= handled || r.name !== name) return null;
  handled = r.seq;
  return r.action;
}

/** Runs a `PORT ...` command. true/false = finished here; string[] = show `PORT <args>`. */
export function portCommand(args: string[], security?: SecurityRef): boolean | string[] {
  const act = parsePort(args, security);
  switch (act.kind) {
    case "error":
      return fail(act.message);
    case "delete":
      statusMsg.set(() => null);
      void deletePortfolio(act.name);
      return true;
    case "view":
      return act.name ? [act.name] : [];
    case "add":
      void addPosition(act.name, { symbol: act.symbol, qty: act.qty, cost: act.cost, ...(act.currency ? { currency: act.currency } : {}) });
      return [act.name];
    case "remove":
      void removePositions(act.name, act.symbols);
      return [act.name];
    case "base":
      void setBase(act.name, act.base);
      return [act.name];
    case "export":
    case "import":
      portfolioRequest.set((r) => ({ name: act.name, action: act.kind as "export" | "import", seq: (r?.seq ?? 0) + 1 }));
      return [act.name];
  }
}
