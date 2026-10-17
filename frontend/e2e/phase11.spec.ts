import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";

/*
 * Phase 11 (spec: docs/specs/PHASE_11.md): APIKEYS, the KEY REQUIRED line, JOBS.
 * Written before the code: each test calls test.fail() until its build step lands; that step deletes the call.
 */

const SECRET = "sk-or-v1-e2e0123456789SECRET";
const now = () => Date.now() / 1000;
const NAMES = ["openrouter", "openai", "anthropic", "finnhub", "alpaca", "fmp", "fred", "eia", "openfigi", "tradier", "telegram", "smtp"];
const FIELDS: Record<string, string[]> = { alpaca: ["ALPACA_KEY_ID", "ALPACA_SECRET_KEY"], smtp: ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"] };

let ws: WebSocketRoute | null = null;

async function setup(page: Page) {
  ws = null;
  const keys = new Map(NAMES.map((n) => [n, {
    name: n, present: false, source: null as string | null, state: "MISSING", checked_at: null as number | null, detail: null,
    fields: FIELDS[n] ?? [`${n.toUpperCase()}_API_KEY`], purpose: `${n} purpose`, phase: 11, signup: `https://example.com/${n}`,
  }]));
  const puts: unknown[] = [];
  const history: string[] = [];
  const deletes: string[] = [];
  await page.routeWebSocket(/\/ws$/, (route) => {
    ws = route;
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/cmdhistory**", (r) => {
    if (r.request().method() === "POST") history.push(r.request().postData() ?? "");
    return r.fulfill({ json: { items: [] } });
  });
  await page.route("**/api/keys**", (r) => {
    const req = r.request();
    const name = new URL(req.url()).pathname.split("/api/keys")[1].replace(/^\//, "").split("/")[0];
    if (!name) return r.fulfill({ json: { keys: [...keys.values()], spend: { today: 0, cap: 1 } } });
    const row = keys.get(name)!;
    if (req.method() === "PUT") {
      puts.push(req.postDataJSON());
      Object.assign(row, { present: true, source: "keyring", state: "OK", checked_at: now() });
    }
    if (req.method() === "DELETE") Object.assign(row, { present: false, source: null, state: "MISSING", checked_at: null });
    return r.fulfill({ json: row });
  });
  await page.route("**/api/fa?**", (r) =>
    r.fulfill({ status: 424, json: { error: "KEY REQUIRED", kind: "key_required", key: "FINNHUB", detail: "KEY REQUIRED: set FINNHUB in APIKEYS" } }));
  await page.route("**/api/jobs**", (r) => {
    const req = r.request();
    if (req.method() === "POST") return r.fulfill({ json: { id: "j1", kind: "sleep", label: "TEST JOB", state: "queued", progress: 0, msg: "", cached: false, created_at: now() } });
    if (req.method() === "DELETE") {
      deletes.push(new URL(req.url()).pathname);
      return r.fulfill({ json: { id: "j1", state: "cancelled" } });
    }
    return r.fulfill({ json: { jobs: [] } });
  });
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  return { keys, puts, history, deletes };
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");
const job = (state: string, progress: number, msg = "") =>
  ws!.send(JSON.stringify(["J", { id: "j1", kind: "sleep", state, progress, msg, cached: false }]));

test("APIKEYS: lists providers, saves a key through the masked field, never shows or records it", async ({ page }) => {
  test.fail();
  const { puts, history } = await setup(page);
  await run(page, "APIKEYS");
  const p = panel(page);
  await expect(p.locator(".ph")).toContainText("APIKEYS");
  await expect(selected(page)).toContainText("OPENROUTER");
  await expect(selected(page)).toContainText("MISSING");

  await page.keyboard.press("Enter"); // edit OPENROUTER
  const field = p.locator("input[type=password]");
  await expect(field).toBeFocused();
  await page.keyboard.type(SECRET);
  await expect(p.getByText("••••CRET")).toBeVisible();
  await page.keyboard.press("Enter"); // save + test
  await expect(selected(page)).toContainText("OK");
  expect(puts).toEqual([{ fields: { OPENROUTER_API_KEY: SECRET } }]);

  expect(await page.content()).not.toContain(SECRET);
  expect(await page.content()).not.toContain("CRET"); // after save even the last 4 characters are gone
  expect(history.join("\n")).not.toContain(SECRET);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(SECRET);
});

test("APIKEYS: Esc cancels an edit, D twice deletes", async ({ page }) => {
  test.fail();
  const { keys, puts } = await setup(page);
  keys.get("openrouter")!.present = true;
  Object.assign(keys.get("openrouter")!, { source: "keyring", state: "OK" });
  await run(page, "APIKEYS");
  await expect(selected(page)).toContainText("OK");
  await page.keyboard.press("Enter");
  await page.keyboard.type("abc");
  await page.keyboard.press("Escape");
  expect(puts).toHaveLength(0);
  await page.keyboard.press("d");
  await page.keyboard.press("d");
  await expect(selected(page)).toContainText("MISSING");
});

test("KEY REQUIRED: a 424 shows the amber line, Enter opens APIKEYS on that provider", async ({ page }) => {
  test.fail();
  await setup(page);
  await run(page, "AAPL FA");
  const line = panel(page).locator(".keyreq");
  await expect(line).toContainText("KEY REQUIRED: set FINNHUB in APIKEYS");
  await page.keyboard.press("Enter");
  await expect(panel(page).locator(".ph")).toContainText("APIKEYS");
  await expect(selected(page)).toContainText("FINNHUB");
});

test("JOBS: JOBS TEST streams progress, Esc cancels, status bar counts running jobs", async ({ page }) => {
  test.fail();
  const { deletes } = await setup(page);
  await run(page, "JOBS TEST 20 50");
  await expect(panel(page).locator(".ph")).toContainText("JOBS");
  await expect.poll(() => ws !== null).toBe(true);
  job("running", 0.5, "step 10/20");
  await expect(selected(page)).toContainText("#####.....  50%");
  await expect(selected(page)).toContainText("TEST JOB");
  await expect(page.locator("footer.status")).toContainText("JOBS 1");
  await page.keyboard.press("Escape");
  await expect.poll(() => deletes).toEqual(["/api/jobs/j1"]);
  job("cancelled", 0.5);
  await expect(selected(page)).toContainText("CANCELLED");
  await expect(page.locator("footer.status")).not.toContainText("JOBS 1");
});
