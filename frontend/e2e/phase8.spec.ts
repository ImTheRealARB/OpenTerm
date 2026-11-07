import { readFile } from "node:fs/promises";
import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import { openApp } from "./app";

const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const PRICES: Record<string, number> = { AAPL: 200, MSFT: 400, NVDA: 100, "SAP.DE": 120, "EURUSD=X": 1.08523 };
const CCY: Record<string, string> = { "SAP.DE": "EUR" };
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: CCY[symbol] ?? "USD", exchange: "X", tz: "America/New_York", price, prev_close: price * 0.99,
  change: price * 0.01, change_pct: 1.01, open: null, high: price * 1.01, low: price * 0.98, volume: 1000, high_52w: null,
  low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});

interface Pos { symbol: string; qty: number; cost: number | null; currency: string | null; notes: string | null }
interface Al { id: number; symbol: string; op: string; unit: string; value: number; status: string; created_at: number; triggered_at: number | null; trigger_price: number | null }

let ws: WebSocketRoute | null = null;
const subs: string[][] = [];

/** What GET /api/alerts/engine answers: the server engine is running and this is NOT fixture mode, so it owns real data. */
const ENGINE = { running: true, note: "ACTIVE WHILE OPENTERM RUNNING", watching: [], last_tick_age_s: null, last_news_poll_age_s: null, fixtures: false, skipped: [] };

/** Mocked quote feed, WebSocket, and stateful in-memory /api/portfolios and /api/alerts (average-cost lots like the backend). */
async function setup(page: Page) {
  ws = null;
  subs.length = 0;
  const books = new Map<string, { base: string; positions: Pos[] }>();
  const alerts: Al[] = [];
  const triggers: { id: number; price: number }[] = [];
  let nextId = 1;
  await page.routeWebSocket(/\/ws$/, (route) => {
    ws = route;
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "sub") subs.push(msg[1]);
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, PRICES[s] ?? 100 + i))])) } });
  });
  // News keyword alerts: none exist in these tests. Without this mock the list and "clear triggered" calls fail (HTTP 500
  // from the unmocked dev backend), and ALRT now says so ("NEWS ALERTS NOT CLEARED", "STALE: NEWS ALERTS ...").
  await page.route("**/api/newsalerts**", (r) => r.fulfill({ json: r.request().method() === "DELETE" ? { deleted: 0 } : { alerts: [] } }));
  await page.route("**/api/portfolios**", (r) => {
    const req = r.request();
    const name = decodeURIComponent(new URL(req.url()).pathname.split("/api/portfolios")[1].replace(/^\//, ""));
    const body = req.postDataJSON?.() ?? null;
    const lot = (p: Pos[], x: { symbol: string; qty: number; cost?: number | null }) => {
      const cur = p.find((q) => q.symbol === x.symbol);
      if (!cur) return p.push({ symbol: x.symbol, qty: x.qty, cost: x.cost ?? null, currency: null, notes: null });
      const qty = cur.qty + x.qty;
      if (Math.sign(cur.qty) === Math.sign(x.qty) && cur.cost != null && x.cost != null) cur.cost = (cur.qty * cur.cost + x.qty * x.cost) / qty;
      cur.qty = qty;
    };
    const out = (n: string) => ({ name: n, ...books.get(n)!, updated_at: now() });
    if (!name) {
      const list = [...books].map(([n, b]) => ({ name: n, base: b.base, count: b.positions.length, updated_at: now() }));
      return r.fulfill({ json: { portfolios: list.sort((a, b) => a.name.localeCompare(b.name)) } });
    }
    const cur = books.get(name);
    if (req.method() === "PATCH") {
      const b = cur ?? { base: "USD", positions: [] };
      books.set(name, b);
      for (const x of body.add ?? []) lot(b.positions, x);
      for (const x of body.set ?? []) {
        const i = b.positions.findIndex((q) => q.symbol === x.symbol);
        const p = { symbol: x.symbol, qty: x.qty, cost: x.cost ?? null, currency: x.currency ?? null, notes: x.notes ?? null };
        if (i < 0) b.positions.push(p);
        else b.positions[i] = p;
      }
      b.positions = b.positions.filter((q) => !(body.remove ?? []).includes(q.symbol));
      if (body.base) b.base = body.base;
      return r.fulfill({ json: out(name) });
    }
    if (req.method() === "PUT") {
      books.set(name, { base: body.base ?? cur?.base ?? "USD", positions: body.positions.map((x: Partial<Pos> & { symbol: string; qty: number }) => ({ cost: null, currency: null, notes: null, ...x })) });
      return r.fulfill({ json: out(name) });
    }
    if (!cur) return r.fulfill({ status: 404, json: { error: `NO PORTFOLIO ${name}`, kind: "not_found" } });
    if (req.method() === "DELETE") {
      books.delete(name);
      return r.fulfill({ json: { deleted: name } });
    }
    return r.fulfill({ json: out(name) });
  });
  await page.route("**/api/alerts**", (r) => {
    const req = r.request();
    const u = new URL(req.url());
    const rest = u.pathname.split("/api/alerts")[1].replace(/^\//, "").split("/");
    if (rest[0] === "engine") return r.fulfill({ json: ENGINE }); // Phase 20: the server engine's state (not fixture mode)
    const id = Number(rest[0]);
    const body = req.postDataJSON?.() ?? null;
    const find = () => alerts.find((a) => a.id === id);
    if (!rest[0]) {
      if (req.method() === "POST") {
        const a: Al = { id: nextId++, ...body, status: "active", created_at: now(), triggered_at: null, trigger_price: null };
        alerts.push(a);
        return r.fulfill({ json: a });
      }
      if (req.method() === "DELETE") {
        const gone = alerts.filter((a) => a.status === u.searchParams.get("status"));
        for (const a of gone) alerts.splice(alerts.indexOf(a), 1);
        return r.fulfill({ json: { deleted: gone.length } });
      }
      return r.fulfill({ json: { alerts } });
    }
    const a = find();
    if (!a) return r.fulfill({ status: 404, json: { error: `NO ALERT ${id}`, kind: "not_found" } });
    if (req.method() === "DELETE") {
      alerts.splice(alerts.indexOf(a), 1);
      return r.fulfill({ json: { deleted: id } });
    }
    if (rest[1] === "trigger") {
      const changed = a.status === "active";
      if (changed) Object.assign(a, { status: "triggered", trigger_price: body.price, triggered_at: body.at });
      if (changed) triggers.push({ id, price: body.price });
      return r.fulfill({ json: { alert: a, changed } });
    }
    Object.assign(a, { status: "active", triggered_at: null, trigger_price: null }); // rearm
    return r.fulfill({ json: a });
  });
  await openApp(page);
  return { books, alerts, triggers };
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape"); // leave the command line: letters go to the panel
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
/** The canvas grid mirrors its selected row into a visually hidden live region. */
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");
const tick = (symbol: string, price: number, change: number | null = null, pct: number | null = null) =>
  ws!.send(JSON.stringify(["T", [[symbol, price, change, pct, null, null, null, Date.now(), "s"]]])); // "s" = SYNTHETIC: the browser fires only on labelled test data (Phase 20)

test("PORT: ADD lots (average cost), P&L and totals, RM, index", async ({ page }) => {
  await setup(page);
  await run(page, "PORT CORE ADD AAPL 10 150");
  const p = panel(page);
  await expect(page.locator(".msg")).toContainText("PORT CORE: ADDED 10 AAPL @ 150");
  await expect(p.locator(".ph")).toContainText("PORT");
  await expect(p).toContainText("PORTFOLIO CORE");
  await expect(p).toContainText("1 POSITIONS");
  await expect(p).toContainText("BASE USD");
  await expect(selected(page)).toContainText("AAPL");
  await expect(selected(page)).toContainText("QTY 10");
  await expect(selected(page)).toContainText("AVG COST 150.00");
  await expect(selected(page)).toContainText("LAST 200.00");
  await expect(selected(page)).toContainText("DAY P&L +20.00");
  await expect(selected(page)).toContainText("MKT VAL 2,000.00");
  await expect(selected(page)).toContainText("UNRL P&L +500.00");
  await expect(selected(page)).toContainText("UNRL % +33.33%");
  const sum = page.getByTestId("port-summary");
  await expect(sum).toContainText("TOTAL USD MKT VAL 2,000.00");
  await expect(sum).toContainText("UNRL +500.00 (+33.33%)");
  await expect.poll(() => subs.flat()).toContain("AAPL");

  // A second lot averages the cost: 10 @ 150 + 10 @ 170 = 20 @ 160.
  await run(page, "PORT CORE ADD AAPL 10 170");
  await expect(selected(page)).toContainText("QTY 20");
  await expect(selected(page)).toContainText("AVG COST 160.00");
  await expect(selected(page)).toContainText("UNRL P&L +800.00");
  await expect(selected(page)).toContainText("UNRL % +25.00%");

  await run(page, "PORT CORE ADD MSFT 5 300");
  await expect(p).toContainText("2 POSITIONS");
  await expect(sum).toContainText("TOTAL USD MKT VAL 6,000.00");
  await expect(sum).toContainText("DAY +60.00 (+1.01%)");
  await expect(sum).toContainText("UNRL +1,300.00 (+27.66%)");
  await expect(sum).toContainText("COST 4,700.00");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("MSFT");
  await expect(selected(page)).toContainText("WGHT 33.33%");

  // Remove from the command line.
  await run(page, "PORT CORE RM MSFT");
  await expect(page.locator(".msg")).toContainText("REMOVED MSFT FROM CORE");
  await expect(p).toContainText("1 POSITIONS");
  await expect(sum).toContainText("TOTAL USD MKT VAL 4,000.00");

  // The index lists it; Enter opens it.
  await run(page, "PORT");
  await expect(p).toContainText("PORTFOLIOS");
  await expect(p.locator("tr.on")).toContainText("CORE");
  await expect(p.locator("tr.on")).toContainText("USD");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("PORTFOLIO CORE");
});

test("PORT: D removes with a confirm, U undoes", async ({ page }) => {
  await setup(page);
  await run(page, "PORT CORE ADD AAPL 10 150");
  await run(page, "PORT CORE ADD MSFT 5 300");
  const p = panel(page);
  await expect(p).toContainText("2 POSITIONS");
  await page.keyboard.press("d");
  await expect(p).toContainText("REMOVE AAPL? PRESS D AGAIN");
  await page.keyboard.press("d");
  await expect(p).toContainText("1 POSITIONS");
  await expect(page.locator(".msg")).toContainText("REMOVED AAPL FROM CORE. U UNDOES.");
  await page.keyboard.press("u");
  await expect(p).toContainText("2 POSITIONS");
  await expect(page.locator(".msg")).toContainText("PORT CORE: RESTORED");
});

test("PORT: EXPORT downloads a re-importable CSV; V pastes a CSV, previews it, merges it", async ({ page }) => {
  await setup(page);
  await run(page, "PORT CORE ADD AAPL 10 150");
  const p = panel(page);
  await expect(selected(page)).toContainText("LAST 200.00");
  const dl = page.waitForEvent("download");
  await run(page, "PORT CORE EXPORT");
  const d = await dl;
  expect(d.suggestedFilename()).toBe("PORT_CORE_USD.csv");
  const csv = await readFile((await d.path())!, "utf-8");
  expect(csv).toContain("AAPL,10,150");
  expect(csv).toContain(",200,2000,500"); // live columns at export time: last, market value, unrealised

  await page.keyboard.press("v");
  const ta = page.getByLabel("CSV text");
  await ta.fill("symbol,quantity,avg_cost\nNVDA,3,100\nBAD ROW,x,y");
  await page.keyboard.press("Control+Enter");
  const pre = page.getByTestId("port-preview");
  await expect(pre).toContainText("1 ROWS OK");
  await expect(pre).toContainText("1 ERRORS (NOT IMPORTED)");
  await expect(pre).toContainText("NVDA");
  await page.keyboard.press("Enter"); // merge
  await expect(page.locator(".msg")).toContainText("PORT CORE: IMPORTED 1 ROWS (MERGE)");
  await expect(p).toContainText("2 POSITIONS");
});

test("PORT: a non-base currency is converted at live FX and labelled", async ({ page }) => {
  await setup(page);
  await run(page, "PORT EUR ADD SAP.DE 10 100");
  const p = panel(page);
  await expect(p).toContainText("PORTFOLIO EUR");
  await expect(selected(page)).toContainText("SAP.DE");
  // (the canvas mirror only refreshes on selection or row changes, so the converted label is checked in the summary)
  const sum = page.getByTestId("port-summary");
  await expect(sum).toContainText("CONVERTED AT LIVE FX: EURUSD=X");
  await expect(sum).toContainText("TOTAL USD MKT VAL 1,302.28"); // 10 x 120 EUR x 1.08523
  await expect(sum).not.toContainText("NOT IN TOTAL");
  await expect.poll(() => subs.flat()).toContain("EURUSD=X");
});

test("ALRT: price and percent alerts fire on live ticks, flash the status bar, REARM and CLEAR", async ({ page }) => {
  const { triggers, alerts } = await setup(page);
  await run(page, "ALRT AAPL > 210");
  await expect(page.locator(".msg")).toContainText("ALERT SET: AAPL > 210");
  await run(page, "ALRT MSFT -3%");
  await expect(page.locator(".msg")).toContainText("ALERT SET: MSFT -3%");
  const p = panel(page);
  await expect(p).toContainText("2 ACTIVE");
  await expect(p).toContainText("0 TRIGGERED");
  await expect(page.locator("footer.status")).toContainText("ALRT 2");
  expect(alerts.map((a) => `${a.symbol} ${a.op} ${a.unit} ${a.value}`)).toEqual(["AAPL > price 210", "MSFT < pct -3"]);
  await expect(selected(page)).toContainText("AAPL");
  await expect(selected(page)).toContainText("CONDITION > 210");
  await expect.poll(() => subs.flat().sort().join(",")).toContain("AAPL");
  await expect.poll(() => subs.flat()).toContain("MSFT");

  // Below the level: nothing happens. At or above: it fires once.
  tick("AAPL", 209.5);
  tick("MSFT", 390, -10, -2.5);
  await page.waitForTimeout(300);
  await expect(page.locator(".alrt-flash")).toHaveCount(0);
  tick("AAPL", 211);
  const flash = page.locator("footer.status .alrt-flash");
  await expect(flash).toContainText("ALERT 1 AAPL > 210 HIT 211.00");
  await expect(p).toContainText("1 ACTIVE");
  await expect(p).toContainText("1 TRIGGERED");
  await expect.poll(() => triggers).toEqual([{ id: 1, price: 211 }]);
  tick("AAPL", 212); // a fired alert does not fire again
  await page.waitForTimeout(300);
  expect(triggers).toHaveLength(1);
  await expect(selected(page)).toContainText("STATUS TRIGGERED");
  await expect(selected(page)).toContainText("HIT AT 211.00");

  // The percent alert fires on the tick's own percent change vs the previous close.
  tick("MSFT", 386, -14, -3.5);
  await expect(flash).toContainText("ALERT 2 MSFT -3% HIT 386.00");
  await expect(p).toContainText("0 ACTIVE");
  await expect(p).toContainText("2 TRIGGERED");

  // R rearms the selected (triggered) alert.
  await page.keyboard.press("r");
  await expect(page.locator(".msg")).toContainText("ALERT 1 REARMED");
  await expect(p).toContainText("1 ACTIVE");
  await expect(selected(page)).toContainText("STATUS ACTIVE");

  // C twice clears triggered alerts only.
  await page.keyboard.press("c");
  await expect(p).toContainText("CLEAR ALL TRIGGERED? PRESS C AGAIN");
  await page.keyboard.press("c");
  await expect(page.locator(".msg")).toContainText("TRIGGERED ALERTS CLEARED");
  await expect(p).toContainText("1 ACTIVE");
  await expect(p).toContainText("0 TRIGGERED");
  expect(alerts).toHaveLength(1);
  await expect(flash).toBeVisible(); // the flash holds the status bar for 15 s; the count is back after it
});

test("ALRT: DEL by key (confirm) and by command; ALRT CLEAR command; bad input names the problem", async ({ page }) => {
  const { alerts } = await setup(page);
  await run(page, "ALRT AAPL < 150");
  await run(page, "ALRT MSFT > 500");
  await run(page, "ALRT NVDA +5%");
  const p = panel(page);
  await expect(p).toContainText("3 ACTIVE");
  await page.keyboard.press("d");
  await expect(p).toContainText("DELETE ALERT 1? PRESS D AGAIN");
  await page.keyboard.press("d");
  await expect(page.locator(".msg")).toContainText("ALERT 1 DELETED");
  await expect(p).toContainText("2 ACTIVE");
  await run(page, "ALRT DEL 2");
  await expect(page.locator(".msg")).toContainText("ALERT 2 DELETED");
  await expect(p).toContainText("1 ACTIVE");
  expect(alerts.map((a) => a.symbol)).toEqual(["NVDA"]);

  await run(page, "ALRT AAPL 200");
  await expect(page.locator(".msg")).toContainText("PRICE ALERTS NEED > OR <");
  await run(page, "ALRT DEL");
  await expect(page.locator(".msg")).toContainText("ALRT DEL NEEDS AN ALERT ID");
  expect(alerts).toHaveLength(1);

  await run(page, "ALRT CLEAR");
  await expect(page.locator(".msg")).toContainText("TRIGGERED ALERTS CLEARED");
  expect(alerts).toHaveLength(1); // nothing was triggered: the active alert stays
});

// Phase 20: real data is fired by the backend engine only, so the browser must not also fire (no double notification).
test("ALRT: a real (non-synthetic) tick does not fire in the browser; the server's A frame updates the list instead", async ({ page }) => {
  const { triggers, alerts } = await setup(page);
  await run(page, "ALRT AAPL > 210");
  await expect(page.locator(".msg")).toContainText("ALERT SET: AAPL > 210");
  await expect.poll(() => subs.flat()).toContain("AAPL");
  ws!.send(JSON.stringify(["T", [["AAPL", 215, null, null, null, null, null, Date.now(), "y"]]]));
  await page.waitForTimeout(400);
  await expect(page.locator(".alrt-flash")).toHaveCount(0);
  expect(triggers).toHaveLength(0); // the browser never called the trigger route
  // The server fires it (here: the mocked backend flips the row), then pushes an "A" frame. This tab only shows it.
  Object.assign(alerts[0], { status: "triggered", trigger_price: 215.5, triggered_at: now() });
  ws!.send(JSON.stringify(["A", "price", alerts[0].id]));
  await expect(page.locator(".alrt-flash")).toContainText("ALERT 1 AAPL > 210 HIT 215.50");
  expect(triggers).toHaveLength(0); // still no browser trigger call: nothing was reported twice
});

test("ALRT panel shows the server engine: its honest limit and every refused match", async ({ page }) => {
  await setup(page);
  await page.route("**/api/alerts/engine", (r) =>
    r.fulfill({ json: { ...ENGINE, watching: ["AAPL"], last_tick_age_s: 2.5, skipped: [{ key: "price:1", label: "AAPL > 210", reason: "STALE TICK 300s OLD", age_s: 12 }] } }),
  );
  await run(page, "ALRT");
  await expect(page.getByTestId("alrt-engine")).toContainText("ACTIVE WHILE OPENTERM RUNNING");
  await expect(page.getByTestId("alrt-engine")).toContainText("WATCHING AAPL");
  await expect(page.getByTestId("alrt-skipped")).toContainText("NOT FIRED: AAPL > 210: STALE TICK 300s OLD");
});
