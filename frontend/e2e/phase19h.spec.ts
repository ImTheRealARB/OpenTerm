import { expect, test } from "@playwright/test";
import { env, panel, run, setup } from "./p19util";

// Phase 19 step 7 end-to-end tests (mocked routes only): CDEP, FUND, LIQ, STBL, DEFI and the not-built UNLK. Numbers are made-up test data.

const T = Date.UTC(2026, 9, 18, 12, 0, 0);
const lv = (px: number, qty: number, cq: number) => [px, qty, cq, cq * px];
const CDEP = {
  base: "BTC", quote: "USDT", symbol: "BTC-USDT", venue: "OKX SPOT", ts_ms: T, usd: true,
  bids: [lv(100, 1, 1), lv(99, 2, 3), lv(98, 3, 6)], asks: [lv(101, 1, 1), lv(102, 1, 2)],
  best_bid: 100, best_ask: 101, mid: 100.5, spread: 1, spread_pct: 0.995, imbalance_pct: 50, bid_qty: 6, ask_qty: 2, levels: [3, 2],
  bands: [{ pct: 0.1, bid: 0, ask: 0, imbalance_pct: null }, { pct: 0.5, bid: 100, ask: 101, imbalance_pct: -0.5 }, { pct: 1, bid: 100, ask: 101, imbalance_pct: -0.5 }],
};
const perp = (base: string, rate: number, extra = {}) => ({
  sym: `${base}USDT`, base, kind: "PERP", mark: 101, index: 100, basis_pct: 1, rate_pct: rate, interval_h: 8, ann_pct: rate * 3 * 365, next_ms: Date.now() + 3_600_000,
  expiry: null, days: null, ann_basis_pct: null, source: "binance", ...extra,
});
const BOARD = {
  mode: "BOARD", venue: "BINANCE", majors: ["BTC", "ETH"], detail: null,
  rows: [perp("BTC", 0.01), perp("ETH", -0.005, { interval_h: 4 }),
    { ...perp("BTC", 0), sym: "BTCUSDT_261225", kind: "QUARTERLY", rate_pct: null, interval_h: null, ann_pct: null, next_ms: null, expiry: "2026-12-25", days: 68, basis_pct: 2, ann_basis_pct: 10.74 }],
};
const DETAIL = {
  mode: "DETAIL", venue: "BINANCE", majors: ["BTC"], rows: [perp("BTC", 0.01)],
  detail: { interval_h: 8, mean_rate_pct: 0.0075, mean_ann_pct: 8.2125, prints: [{ t: T - 28_800_000, rate_pct: 0.005, ann_pct: 5.475 }, { t: T, rate_pct: 0.01, ann_pct: 10.95 }] },
};
const ev = (t: number, side: string, px: number, usd: number) => ({ t, side, px, base: usd / px, usd, inst: "BTC-USDT-SWAP" });
const LIQ = {
  base: "BTC", venue: "OKX", events: 2, span_s: 720, since_ms: T - 720_000, until_ms: T, long: { n: 1, usd: 250000 }, short: { n: 1, usd: 1500 },
  largest: ev(T - 720_000, "LONG", 80000, 250000), recent: [ev(T, "SHORT", 81000, 1500), ev(T - 720_000, "LONG", 80000, 250000)], ct_val: 0.01,
  note: "OKX RETURNS ONLY THE LATEST FILLED LIQUIDATION ORDERS (ABOUT 100), NOT A FIXED WINDOW. BINANCE PUBLISHES NO LIQUIDATION HISTORY OVER REST.",
};
const coin = (symbol: string, value: number, price: number) => ({
  name: `${symbol} COIN`, symbol, peg: "peggedUSD", mechanism: "fiat-backed", circulating: value, value, chg_1d: 0.1, chg_7d: -0.2, chg_30d: 1.5, price,
  peg_dev_pct: (price - 1) * 100, chains: ["Ethereum", "Tron"],
});
const STBL = (chain: string | null) => ({
  coins: [coin("USDT", 1.5e11, 1.0001), coin("USDC", 7e10, 0.993)], chains: [{ chain: "Ethereum", usd: 1.2e11, share_pct: 54.5 }, { chain: "Tron", usd: 7e10, share_pct: 31.8 }],
  total_usd: chain ? 7e10 : 2.2e11, n_coins: 2, chain,
});
const pool = (project: string, chain: string, apy: number) => ({ chain, project, symbol: "USDC-WETH", tvl: 5e7, apy, apy_base: apy, apy_reward: null, stable: false, il: "yes", apy_30d: 3.2, pool: project });
const DEFI = { rows: [pool("uniswap-v3", "Ethereum", 12.5), pool("aave-v3", "Ethereum", 4.1)], matched: 2, mode: "CHAIN", query: "ethereum", pools_over_tvl: 360, min_tvl: 1_000_000 };

test("CDEP: OKX fallback is named, ladder best first, spread and imbalance; F5 refetches", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/cdep?**", (r) => {
    asked.push(new URL(r.request().url()).searchParams.get("pair") ?? "");
    return r.fulfill({ json: env(CDEP, { source: "okx", fallback_from: ["binance_deriv"] }) });
  });
  await run(page, "CDEP BTC-USDT 10");
  const p = panel(page);
  await expect(p).toContainText("CDEP ORDER BOOK · BTC-USDT · OKX SPOT");
  await expect(p).toContainText("BINANCE_DERIV DOWN, VIA FALLBACK");
  await expect(p.getByTestId("cdep-summary")).toContainText("MID 100.50");
  await expect(p.getByTestId("cdep-summary")).toContainText("IMBALANCE +50.0%");
  await expect(p.locator(".sr")).toContainText("100.00");
  await expect(p.locator(".sr")).toContainText("101.00");
  expect(asked[0]).toBe("BTC-USDT");
  const n = asked.length;
  await page.keyboard.press("F5");
  await expect.poll(() => asked.length).toBeGreaterThan(n);
  expect(errors).toEqual([]);
});

test("FUND: board shows annualised funding and quarterly basis; Enter opens the coin's history, Backspace returns", async ({ page }) => {
  const { errors } = await setup(page);
  const syms: string[] = [];
  await page.route("**/api/world/fund?**", (r) => {
    const sym = new URL(r.request().url()).searchParams.get("sym") ?? "";
    syms.push(sym);
    return r.fulfill({ json: env(sym ? DETAIL : BOARD, { source: "binance_deriv" }) });
  });
  await run(page, "FUND");
  const p = panel(page);
  await expect(p).toContainText("FUND PERPETUAL FUNDING · MAJORS");
  await expect(p).toContainText("NOT ANNUALISED");
  await expect(p.locator(".sr")).toContainText("BTCUSDT");
  await expect(p.locator(".sr")).toContainText("+10.95%");
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("2026-12-25 68D");
  await expect(p.locator(".sr")).toContainText("+10.74%");
  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await page.keyboard.press("Enter");
  await expect(p.getByTestId("fund-mean")).toContainText("LAST 2 PRINTS: MEAN +0.0075% EVERY 8H = +8.21% A YEAR");
  expect(syms).toContain("BTC");
  await expect(p.locator(".sr")).toContainText("+0.0100%");
  await page.keyboard.press("Backspace");
  await expect(p).toContainText("· MAJORS");
  expect(errors).toEqual([]);
});

test("LIQ: totals per liquidated side over the span the sample covers, newest first", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/liq?**", (r) => r.fulfill({ json: env(LIQ, { source: "okx" }) }));
  await run(page, "LIQ BTC");
  const p = panel(page);
  await expect(p).toContainText("LIQ LIQUIDATIONS · BTC-USDT PERPETUAL · OKX");
  await expect(p.getByTestId("liq-summary")).toContainText("2 ORDERS OVER 12M");
  await expect(p.getByTestId("liq-summary")).toContainText("LONGS 1 $250.0K");
  await expect(p).toContainText("BINANCE PUBLISHES NO LIQUIDATION HISTORY");
  await expect(p.locator(".sr")).toContainText("SHORT");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("LONG");
  expect(errors).toEqual([]);
});

test("STBL: coins with peg deviation, C switches to chains, Enter opens one chain", async ({ page }) => {
  const { errors } = await setup(page);
  const chains: string[] = [];
  await page.route("**/api/world/stbl?**", (r) => {
    const c = new URL(r.request().url()).searchParams.get("chain") ?? "";
    chains.push(c);
    return r.fulfill({ json: env(STBL(c || null), { source: "defillama" }) });
  });
  await run(page, "STBL");
  const p = panel(page);
  await expect(p.getByTestId("stbl-summary")).toContainText("TOTAL $220.00B ACROSS CHAINS");
  await expect(p.locator(".sr")).toContainText("USDT");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("-0.70%");
  await expect(async () => {
    await page.keyboard.press("c");
    await expect(p).toContainText("ALL CHAINS · CHAINS", { timeout: 500 });
  }).toPass();
  await expect(p.locator(".sr")).toContainText("Ethereum");
  await page.keyboard.press("j");
  await page.keyboard.press("Enter");
  await expect(p.getByTestId("stbl-summary")).toContainText("ON TRON");
  expect(chains).toContain("Tron");
  expect(errors).toEqual([]);
});

test("DEFI: pools by chain, highest APY first, with the TVL cut; UNLK says it is not built", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/defi?**", (r) => r.fulfill({ json: env(DEFI, { source: "defillama" }) }));
  await run(page, "DEFI ETHEREUM");
  const p = panel(page);
  await expect(p).toContainText("DEFI YIELD POOLS · CHAIN ETHEREUM");
  await expect(p.getByTestId("defi-summary")).toContainText("2 POOLS MATCH OF 360 WITH TVL OVER $1.00M");
  await expect(p.locator(".sr")).toContainText("uniswap-v3");
  await expect(p.locator(".sr")).toContainText("12.50%");
  await run(page, "UNLK");
  await expect(p).toContainText("EMISSIONS API IS PAID");
  expect(errors).toEqual([]);
});
