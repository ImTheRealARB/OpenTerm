import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 16 step 5 (spec: docs/specs/PHASE_16.md): SWARM, THESIS and AI AUTO. The backend is mocked with the SSE events and JSON the real routes send
 * (shapes: backend/tests/test_phase16_swarm.py); nothing reaches the network or a model.
 */
type Ev = Record<string, unknown>;
const sse = (events: Ev[]) => events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
const RUN_ID = "0123456789ab";
const ROLES = [
  { id: "fundamental", title: "Fundamental analyst", tools: ["quote", "fa"] },
  { id: "technical", title: "Technical analyst", tools: ["history"] },
  { id: "chair", title: "Chair", tools: ["quote"] },
];
const SWARM_RUN: Ev[] = [
  { type: "swarm_start", preset: "COMMITTEE", title: "Investment committee", subject: "AAPL", model: "deepseek/deepseek-v4-pro", provider: "openrouter", started: "2026-10-18T10:00:00+00:00", roles: ROLES },
  { type: "role_start", role: "fundamental", title: "Fundamental analyst", tools: ["quote", "fa"], attempt: 1 },
  { type: "tool_call", role: "fundamental", id: "T1", name: "quote", args: { symbols: "AAPL" } },
  { type: "tool_result", role: "fundamental", id: "T1", name: "quote", ok: true, empty: false, source: "yahoo:test", age_s: 2.5, stale: false, bytes: 200, summary: "{}" },
  { type: "role_done", role: "fundamental", answer: "Price 343.46 [T1].", grounded: true, label: null, unsourced: [], tool_calls: 1, cost: 0.001, stopped: null },
  { type: "role_start", role: "technical", title: "Technical analyst", tools: ["history"], attempt: 1 },
  { type: "role_error", role: "technical", kind: "provider", text: "PROVIDER DOWN" },
  { type: "role_retry", role: "technical", attempt: 2, why: "provider: PROVIDER DOWN" },
  { type: "role_start", role: "technical", title: "Technical analyst", tools: ["history"], attempt: 2 },
  { type: "role_error", role: "technical", kind: "provider", text: "PROVIDER DOWN" },
  { type: "role_start", role: "chair", title: "Chair", tools: ["quote"], attempt: 1 },
  { type: "role_done", role: "chair", answer: "The desk sees 343.46 and a target of 999.9.", grounded: true, label: null, unsourced: ["999.9"], tool_calls: 0, cost: 0.001, stopped: null },
  { type: "saved", run_id: RUN_ID },
  { type: "swarm_done", answer: "The desk sees 343.46 and a target of 999.9.", roles: [], cost: 0.002, unsourced: ["999.9"], grounded: true, label: null, failed: ["technical"] },
];
const PRESETS = [
  { code: "COMMITTEE", title: "Investment committee", roles: ROLES, note: "Subject: one ticker, e.g. AAPL.", needs_subject: true },
  { code: "MACRO", title: "Macro desk", roles: ROLES.slice(0, 2), note: "Subject: a theme.", needs_subject: false },
];
interface Th { id: number; symbol: string; status: string; text: string; invalidation: string; run_ids: string[]; created_at: number; updated_at: number }

const bodies: Record<string, unknown[]> = {};
const log = (k: string, v: unknown) => (bodies[k] ??= []).push(v);
let theses: Th[] = [];
const H = (c: string) => c.repeat(64);
const MF = { prompt_sha: H("a"), tools_sha: H("b"), tools: ["quote", "history"], app: "0.16.0", skills: {} };
const LEDGER = [
  { seq: 2, at: 1_790_000_100, kind: "swarm", ref: RUN_ID, model: "deepseek/deepseek-v4-pro", manifest: MF, meta: { cost: 0.002, grounded: true, unsourced: 1, tool_calls: [{ id: "T1", role: "fundamental", name: "quote", ok: true, source: "yahoo:test" }] }, prev_hash: H("c"), hash: H("d") },
  { seq: 1, at: 1_790_000_000, kind: "chat", ref: "", model: "deepseek/deepseek-v4-pro", manifest: MF, meta: { cost: 0.001, grounded: false, unsourced: 0, tool_calls: [] }, prev_hash: H("0"), hash: H("c") },
];
let verdict: Record<string, unknown> = { ok: true, count: 2, head: H("d"), broken_at: null, reason: null };

async function setup(page: Page, swarm: Ev[] = SWARM_RUN) {
  for (const k of Object.keys(bodies)) delete bodies[k];
  theses = [
    { id: 1, symbol: "AAPL", status: "open", text: "Services growth carries margins", invalidation: "", run_ids: [RUN_ID], created_at: 1_790_000_000, updated_at: 1_790_000_000 },
    { id: 2, symbol: "MSFT", status: "confirmed", text: "Cloud demand", invalidation: "Azure growth under 20%", run_ids: [], created_at: 1_790_000_000, updated_at: 1_790_100_000 },
  ];
  await page.routeWebSocket(/\/ws$/, (route) =>
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    }),
  );
  await page.route("**/api/llm/health", (r) => r.fulfill({ json: { providers: [], spend: { today: 0.12, cap: 1 } } }));
  await page.route("**/api/ai/swarm/presets", (r) => r.fulfill({ json: { presets: PRESETS } }));
  await page.route("**/api/ai/runs?**", (r) => r.fulfill({ json: { runs: [{ id: RUN_ID, kind: "swarm", title: "COMMITTEE AAPL", symbol: "AAPL", created_at: 1_790_000_000 }] } }));
  await page.route("**/api/ai/swarm", (r) => {
    log("swarm", r.request().postDataJSON());
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse(swarm) });
  });
  await page.route("**/api/ai/runs/*/replay", (r) => {
    log("replay", r.request().url());
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([{ type: "replay", run_id: RUN_ID, kind: "swarm", title: "COMMITTEE AAPL", created_at: 1_790_000_000 }, ...swarm.filter((e) => e.type !== "saved")]) });
  });
  await page.route("**/api/ai/auto", (r) => {
    log("auto", r.request().postDataJSON());
    return r.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sse([
        { type: "start", model: "deepseek/deepseek-v4-pro", provider: "openrouter", started: "2026-10-18T10:00:00+00:00" },
        { type: "tool_call", id: "T1", name: "backtest_run", args: { rule: "SMA20 CROSS> SMA50" } },
        { type: "tool_result", id: "T1", name: "backtest_run", ok: true, empty: false, source: "openterm", age_s: 0, stale: false, bytes: 300, summary: "{}" },
        { type: "evidence", runs: [RUN_ID], tested: true, note: "HISTORICAL SIMULATION, NOT A FORECAST" },
        { type: "saved", run_id: "ba9876543210" },
        { type: "done", answer: "The rule returned 12.3 percent [T1].", grounded: true, label: null, unsourced: [], tool_calls: 1, cost: 0.002, stopped: null },
      ]),
    });
  });
  await page.route("**/api/ai/ledger?**", (r) => r.fulfill({ json: { entries: LEDGER } }));
  await page.route("**/api/ai/ledger/verify", (r) => r.fulfill({ json: verdict }));
  await page.route("**/api/theses**", async (r) => {
    const req = r.request();
    const url = new URL(req.url());
    const id = Number(url.pathname.split("/").pop());
    if (req.method() === "GET") {
      const sym = url.searchParams.get("symbol");
      return r.fulfill({ json: { theses: theses.filter((t) => !sym || t.symbol === sym) } });
    }
    const body = req.postDataJSON() as Record<string, unknown>;
    log("theses " + req.method(), body);
    if (req.method() === "POST") {
      const t: Th = { id: 9, symbol: String(body.symbol), status: "open", text: String(body.text), invalidation: "", run_ids: (body.run_ids as string[]) ?? [], created_at: 1_790_200_000, updated_at: 1_790_200_000 };
      theses = [t, ...theses];
      return r.fulfill({ json: { thesis: t } });
    }
    if (req.method() === "PATCH") {
      theses = theses.map((t) => (t.id === id ? { ...t, ...(body as Partial<Th>) } : t));
      return r.fulfill({ json: { thesis: theses.find((t) => t.id === id) } });
    }
    theses = theses.filter((t) => t.id !== id);
    return r.fulfill({ json: { deleted: id } });
  });
  await openApp(page);
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const swarm = (page: Page) => page.getByTestId("swarm-panel");
const thesis = (page: Page) => page.getByTestId("thesis-panel");

test.describe("SWARM", () => {
  test("a committee run shows each role with its tools, the failed role, the checked desk answer and the stored run", async ({ page }) => {
    await setup(page);
    await run(page, "SWARM COMMITTEE AAPL");
    await expect(swarm(page).getByTestId("swarm-role")).toHaveCount(3);
    const first = swarm(page).locator('[data-role="fundamental"]');
    await expect(first).toContainText("DONE");
    await expect(first).toContainText("[T1] quote");
    await expect(first).toContainText("yahoo:test");
    const tech = swarm(page).locator('[data-role="technical"]');
    await expect(tech).toContainText("FAILED");
    await expect(tech.getByTestId("swarm-role-error")).toHaveCount(3); // retry line + two failures
    await expect(swarm(page).getByTestId("swarm-answer")).toContainText("The desk sees 343.46");
    await expect(swarm(page).getByTestId("swarm-unsourced")).toContainText("999.9");
    await expect(swarm(page)).toContainText("ROLES THAT FAILED: technical");
    await expect(swarm(page).getByTestId("swarm-footer")).toContainText("MODEL OUTPUT, NOT DATA");
    await expect(swarm(page).getByTestId("swarm-footer")).toContainText(`STORED RUN ${RUN_ID}`);
    expect(bodies.swarm[0]).toMatchObject({ preset: "COMMITTEE", subject: "AAPL" });
  });

  test("SWARM lists the presets and the stored runs; REPLAY shows a stored run and says no model was called", async ({ page }) => {
    await setup(page);
    await run(page, "SWARM");
    await expect(swarm(page).getByTestId("swarm-preset")).toHaveCount(2);
    await expect(swarm(page).getByTestId("swarm-stored")).toContainText(RUN_ID);
    await run(page, `SWARM REPLAY ${RUN_ID}`);
    await expect(swarm(page).getByTestId("swarm-replay")).toContainText("NO MODEL WAS CALLED NOW");
    await expect(swarm(page).getByTestId("swarm-answer")).toContainText("343.46");
    expect(bodies.replay).toHaveLength(1);
  });

  test("T saves the desk answer as a THESIS note linked to the run", async ({ page }) => {
    await setup(page);
    await run(page, "SWARM COMMITTEE AAPL");
    await expect(swarm(page).getByTestId("swarm-footer")).toBeVisible();
    await page.keyboard.press("t");
    await expect(swarm(page).getByTestId("swarm-note")).toContainText("SAVED FOR AAPL");
    expect(bodies["theses POST"][0]).toMatchObject({ symbol: "AAPL", run_ids: [RUN_ID] });
    expect(String((bodies["theses POST"][0] as { text: string }).text)).toContain("MODEL OUTPUT");
  });

  test("a missing key shows KEY REQUIRED; a bad preset shows the usage", async ({ page }) => {
    await setup(page, [{ type: "error", kind: "key_required", text: "KEY REQUIRED: set OPENROUTER in APIKEYS" }]);
    await run(page, "SWARM MACRO");
    await expect(swarm(page).getByTestId("swarm-error")).toContainText("KEY REQUIRED");
    await run(page, "SWARM QUANT");
    await expect(swarm(page).getByTestId("swarm-note")).toContainText("USAGE: SWARM QUANT");
  });
});

test.describe("THESIS", () => {
  test("lists notes, S cycles the status, D twice deletes, ADD and INVALID work from the command line", async ({ page }) => {
    await setup(page);
    await run(page, "THESIS");
    await expect(thesis(page).getByTestId("thesis-row")).toHaveCount(2);
    await expect(thesis(page).getByTestId("thesis-detail")).toContainText("Services growth");
    await expect(thesis(page).getByTestId("thesis-detail")).toContainText(`SWARM REPLAY ${RUN_ID}`);
    await expect(thesis(page).getByTestId("thesis-detail")).toContainText("NOT SET");
    await page.keyboard.press("s");
    await expect(thesis(page).getByTestId("thesis-note")).toContainText("THESIS 1 IS NOW CONFIRMED");
    expect(bodies["theses PATCH"][0]).toEqual({ status: "confirmed" });
    await page.keyboard.press("ArrowDown");
    await expect(thesis(page).getByTestId("thesis-detail")).toContainText("Azure growth under 20%");
    await page.keyboard.press("d");
    await expect(thesis(page).getByTestId("thesis-note")).toContainText("PRESS D AGAIN");
    await page.keyboard.press("d");
    await expect(thesis(page).getByTestId("thesis-row")).toHaveCount(1);
    await run(page, "THESIS ADD TSLA Deliveries rebound");
    await expect(thesis(page).getByTestId("thesis-note")).toContainText("THESIS 9 ADDED FOR TSLA");
    expect(bodies["theses POST"][0]).toEqual({ symbol: "TSLA", text: "Deliveries rebound" });
    await run(page, "THESIS INVALID 1 Services growth below 8 percent");
    await expect(thesis(page).getByTestId("thesis-note")).toContainText("INVALIDATION RULE SET FOR THESIS 1");
    await expect(thesis(page).getByTestId("thesis-detail")).toContainText("Services growth below 8 percent");
  });

  test("THESIS <SYMBOL> filters; bad usage says how", async ({ page }) => {
    await setup(page);
    await run(page, "THESIS MSFT");
    await expect(thesis(page).getByTestId("thesis-row")).toHaveCount(1);
    await expect(thesis(page)).toContainText("MSFT");
    await run(page, "THESIS ADD");
    await expect(thesis(page).getByTestId("thesis-note")).toContainText("USAGE: THESIS ADD");
  });
});

test.describe("AI AUTO", () => {
  test("shows the backtest evidence line and the stored run; the AI never runs BT itself", async ({ page }) => {
    await setup(page);
    await run(page, "AI AUTO a 20/50 cross works on AAPL");
    await expect(page.getByTestId("ai-evidence")).toContainText(`BT RUN ${RUN_ID}`);
    await expect(page.getByTestId("ai-evidence")).toContainText("HISTORICAL SIMULATION, NOT A FORECAST");
    await expect(page.getByTestId("ai-evidence")).toContainText("STORED RUN ba9876543210");
    await expect(page.getByTestId("ai-answer")).toContainText("12.3 percent");
    expect(bodies.auto[0]).toMatchObject({ hypothesis: "a 20/50 cross works on AAPL" });
  });
});

test.describe("AUDIT", () => {
  test("shows the verified chain and an entry's manifest and tool calls", async ({ page }) => {
    await setup(page);
    verdict = { ok: true, count: 2, head: H("d"), broken_at: null, reason: null };
    await run(page, "AUDIT");
    await expect(page.getByTestId("audit-verdict")).toContainText("CHAIN OK · 2 ENTRIES · HEAD dddddddddddddddd");
    await expect(page.getByTestId("audit-row")).toHaveCount(2);
    await expect(page.getByTestId("audit-detail")).toContainText("[T1] fundamental quote · yahoo:test · OK");
    await expect(page.getByTestId("audit-detail")).toContainText("1 UNSOURCED NUMBERS");
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("audit-detail")).toContainText("UNGROUNDED");
  });

  test("a broken chain says where", async ({ page }) => {
    await setup(page);
    verdict = { ok: false, count: 2, head: H("c"), broken_at: 2, reason: "ENTRY CONTENT DOES NOT MATCH ITS HASH (IT WAS CHANGED)" };
    await run(page, "AUDIT");
    await expect(page.getByTestId("audit-verdict")).toContainText("CHAIN BROKEN AT ENTRY 2");
  });
});
