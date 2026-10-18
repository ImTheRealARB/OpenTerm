import { expect, test } from "@playwright/test";
import { env, exportCsv, panel, run, setup } from "./p19util";

// Phase 19 step 8 end-to-end tests (mocked routes only): PRED. The rows below are made up for the test; the real recordings are covered by the pytest suite.

const LABEL = "MARKET-IMPLIED PROBABILITY, NOT A FORECAST";
const poly = (id: string, question: string, prob: number, volume: number, outcome = "Yes") => ({
  id, source: "polymarket", question, outcome, prob, pct: Math.round(prob * 1000) / 10, volume, vol_unit: "USD", close: "2027-01-01", history: true, ref: id, event: null,
});
const kalshi = (id: string, question: string, prob: number, volume: number) => ({
  id, source: "kalshi", question, outcome: "Yes", prob, pct: Math.round(prob * 1000) / 10, volume, vol_unit: "contracts", close: "2026-12-31", history: true, ref: "KXFED", event: null, basis: "last",
});
const ROWS = [
  poly("p1", "Will the test invade Mars before 2027?", 0.145, 74_580_410),
  poly("p2", "Who wins the test final?", 0.41, 3_200_000, "Lakers"),
  kalshi("KXFED-27-T", "Will the Fed cut rates in December?", 0.62, 211_127),
];
const payload = (rows = ROWS, extra = {}) => ({
  rows, label: LABEL, q: "", counts: { polymarket: 2, kalshi: 1 }, failed: [], notes: [], sources: ["polymarket", "kalshi"],
  unit_note: "VOLUME: POLYMARKET IN USD, KALSHI IN CONTRACTS OF US$1 (NOT THE SAME UNIT)", ...extra,
});
const T = Array.from({ length: 60 }, (_, i) => 1_790_000_000 + i * 14_400);
const detail = (source: string, id: string, withHistory = true) => ({
  source, id, question: source === "kalshi" ? "Will the Fed cut rates in December?" : "Will the test invade Mars before 2027?", label: LABEL, open: true,
  volume: 74_580_410, vol_unit: source === "kalshi" ? "contracts" : "USD", liquidity: source === "kalshi" ? null : 496_571, open_interest: source === "kalshi" ? 55_126 : undefined,
  close: "2027-01-01", outcomes: [
    { name: "Yes", prob: 0.145, pct: 14.5, bid: source === "kalshi" ? 0.14 : null, ask: source === "kalshi" ? 0.15 : null },
    { name: "No", prob: 0.855, pct: 85.5, bid: source === "kalshi" ? 0.85 : null, ask: source === "kalshi" ? 0.86 : null }],
  lead: "Yes", history: withHistory ? { t: T, p: T.map((_, i) => 0.1 + 0.002 * i) } : null, history_outcome: "Yes",
  history_note: withHistory ? null : "NO TRADES IN THE LAST 7 DAYS: NOTHING TO CHART", basis: source === "kalshi" ? "last traded price" : "outcome price",
});

const LIST = /\/api\/world\/pred(\?|$)/;
const DETAIL = /\/api\/world\/pred\/detail\?/;

test("PRED: rows from both sources with the label, YES percent and volume units; Enter opens outcomes and a history chart, Esc closes it", async ({ page }) => {
  const { errors } = await setup(page);
  const calls: string[] = [];
  await page.route(LIST, (r) => {
    calls.push(new URL(r.request().url()).searchParams.get("q") ?? "");
    return r.fulfill({ json: env(payload(), { source: "polymarket + kalshi" }) });
  });
  const details: string[] = [];
  await page.route(DETAIL, (r) => {
    const u = new URL(r.request().url());
    details.push(`${u.searchParams.get("source")}|${u.searchParams.get("id")}`);
    return r.fulfill({ json: env(detail(u.searchParams.get("source")!, u.searchParams.get("id")!), { source: u.searchParams.get("source")! }) });
  });
  await run(page, "PRED");
  const p = panel(page);
  await expect(p.getByTestId("pred-label")).toContainText(LABEL);
  await expect(p).toContainText("3 MARKETS");
  await expect(p).toContainText("POLYMARKET + KALSHI");
  await expect(p).toContainText("NOT THE SAME UNIT");
  await expect(p.locator(".sr")).toContainText("Will the test invade Mars before 2027?");
  await expect(p.locator(".sr")).toContainText("14.5%");
  await expect(p.locator(".sr")).toContainText("$74.6M");
  await expect(p.locator(".sr")).toContainText("POLYMARKET");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("41.0% LAKERS");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("211.1K ct");
  await expect(p.locator(".sr")).toContainText("KALSHI");

  await page.keyboard.press("Enter");
  const d = p.getByTestId("pred-detail");
  await expect(d).toContainText("KALSHI");
  await expect(d).toContainText("BID 14.0%  ASK 15.0%");
  await expect(d).toContainText("OPEN INTEREST 55126 ct");
  await expect(d).toContainText(LABEL);
  await expect(d.locator(".chart")).toBeVisible();
  expect(details).toEqual(["kalshi|KXFED-27-T"]);

  await page.keyboard.press("Escape");
  await expect(d).toHaveCount(0);
  expect(calls).toEqual([""]);
  expect(errors).toEqual([]);
});

test("PRED: text words go to the server as the filter; SRC= keeps one source; a miss still shows the label", async ({ page }) => {
  await setup(page);
  const calls: string[] = [];
  await page.route(LIST, (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    calls.push(q);
    const rows = ROWS.filter((x) => q.split(" ").every((w) => x.question.toLowerCase().includes(w.toLowerCase())));
    return r.fulfill({ json: env(payload(rows, { q }), { source: "polymarket + kalshi" }) });
  });
  await run(page, "PRED fed cut SRC=KALSHI");
  const p = panel(page);
  await expect(p).toContainText("FED CUT");
  await expect(p).toContainText("KALSHI ONLY");
  await expect(p).toContainText("1 MARKETS");
  await expect(p.locator(".sr")).toContainText("Will the Fed cut rates in December?");
  expect(calls).toEqual(["fed cut"]);
  await run(page, "PRED zzqqxxvv");
  await expect(p).toContainText("NO OPEN MARKET MATCHES ZZQQXXVV");
  await expect(p.getByTestId("pred-label")).toContainText(LABEL);
  await run(page, "PRED mars SRC=KALSHI");
  await expect(p).toContainText("NO OPEN MARKET MATCHES MARS ON KALSHI");
});

test("PRED: one source down is named and the other still answers; both down is an error with no table", async ({ page }) => {
  await setup(page);
  let mode: "one" | "both" = "one";
  await page.route(LIST, (r) => {
    if (mode === "both") {
      return r.fulfill({ status: 502, json: { error: "PROVIDER DOWN: POLYMARKET AND KALSHI BOTH FAILED", kind: "unavailable", detail: "polymarket: timeout; kalshi: HTTP 503" } });
    }
    return r.fulfill({
      json: env(payload(ROWS.slice(0, 2), { failed: [{ source: "kalshi", reason: "unavailable (timeout)" }], notes: ["KALSHI FAILED (unavailable (timeout)): ROWS ARE POLYMARKET ONLY"], sources: ["polymarket"] }),
        { source: "polymarket", fallback_from: ["kalshi"] }),
    });
  });
  await run(page, "PRED");
  const p = panel(page);
  await expect(p).toContainText("KALSHI FAILED");
  await expect(p).toContainText("ROWS ARE POLYMARKET ONLY");
  await expect(p).toContainText("2 MARKETS");
  await expect(p.getByTestId("pred-label")).toContainText(LABEL);
  mode = "both";
  await page.keyboard.press("F5");
  await expect(p).toContainText("POLYMARKET AND KALSHI BOTH FAILED");
  await expect(p).not.toContainText("MARKETS ·");
  await expect(p.getByTestId("pred-label")).toContainText(LABEL);
});

test("PRED: a market with no price history says so instead of drawing a chart", async ({ page }) => {
  await setup(page);
  await page.route(LIST, (r) => r.fulfill({ json: env(payload(), { source: "polymarket + kalshi" }) }));
  await page.route(DETAIL, (r) => r.fulfill({ json: env(detail("polymarket", "p1", false), { source: "polymarket" }) }));
  await run(page, "PRED");
  const p = panel(page);
  await expect(p.locator(".sr")).toContainText("14.5%");
  await page.keyboard.press("Enter");
  await expect(p.getByTestId("pred-history-note")).toContainText("NOTHING TO CHART");
  await expect(p.getByTestId("pred-detail")).toContainText("LIQUIDITY $496571");
  await expect(p.getByTestId("pred-detail").locator(".chart")).toHaveCount(0);
});

test("PRED: a bad SRC shows usage and the label; E exports the table as CSV", async ({ page }) => {
  await setup(page);
  await page.route(LIST, (r) => r.fulfill({ json: env(payload(), { source: "polymarket + kalshi" }) }));
  await run(page, "PRED x SRC=ftx");
  const p = panel(page);
  await expect(p).toContainText("SRC MUST BE POLY, KALSHI OR ALL");
  await expect(p.getByTestId("pred-label")).toContainText(LABEL);
  await run(page, "PRED");
  await expect(p.locator(".sr")).toContainText("14.5%");
  const csv = await exportCsv(page);
  expect(csv.name).toContain("PRED_ALL");
  expect(csv.text).toContain("QUESTION");
  expect(csv.text).toContain("Will the Fed cut rates in December?");
  expect(csv.text).toContain("211.1K ct");
});
