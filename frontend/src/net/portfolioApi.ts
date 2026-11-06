/** Portfolios (PORT and the quant panels that read holdings) and their valuation history. Uncached (`send`). */
import { send } from "./core";
import type { Portfolio, PortfolioInfo, PositionIn, ValRow } from "./types";

const pf = (name: string) => `/api/portfolios/${encodeURIComponent(name)}`;

export const portfolioApi = {
  portfolios: () => send<{ portfolios: PortfolioInfo[] }>("GET", "/api/portfolios"),
  portfolio: (name: string) => send<Portfolio>("GET", pf(name)),
  putPortfolio: (name: string, positions: PositionIn[], base?: string) =>
    send<Portfolio>("PUT", pf(name), base ? { positions, base } : { positions }),
  editPortfolio: (name: string, change: { add?: PositionIn[]; set?: PositionIn[]; remove?: string[]; base?: string }) =>
    send<Portfolio>("PATCH", pf(name), change),
  deletePortfolio: (name: string) => send<{ deleted: string }>("DELETE", pf(name)),
  vals: (name: string) => send<{ rows: ValRow[] }>("GET", `${pf(name)}/vals`),
  putVals: (name: string, rows: ValRow[]) => send<{ rows: ValRow[] }>("PUT", `${pf(name)}/vals`, { rows }),
};
