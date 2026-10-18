import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 16 step 2 (spec: docs/specs/PHASE_16.md): the AI panel. The backend agent is replaced by a mocked `POST /api/ai/chat` that answers with the
 * SSE events the real route sends (recorded shapes: see backend/tests/test_phase16_agent.py); nothing reaches the network or a model.
 */
type Ev = Record<string, unknown>;
const sse = (events: Ev[]) => events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
const START = { type: "start", model: "deepseek/deepseek-v4-pro", provider: "openrouter", started: "2026-10-18T10:00:00+00:00" };
const GROUNDED: Ev[] = [
  START,
  { type: "tool_call", id: "T1", name: "quote", args: { symbols: "AAPL" } },
  { type: "tool_result", id: "T1", name: "quote", ok: true, empty: false, source: "yahoo:test", age_s: 2.5, stale: false, bytes: 200, summary: "{}" },
  { type: "token", text: "AAPL is at 343.46 " },
  { type: "token", text: "[T1]." },
  { type: "usage", prompt_tokens: 100, completion_tokens: 20, cost: 0.0012 },
  { type: "done", answer: "AAPL is at 343.46 [T1].", grounded: true, label: null, unsourced: [], tool_calls: 1, cost: 0.0012, stopped: null },
];

const bodies: { question: string; model: string; provider: string; history: { role: string; content: string }[] }[] = [];

async function setup(page: Page, answers: Ev[][] | "hang" = [GROUNDED]) {
  bodies.length = 0;
  await page.routeWebSocket(/\/ws$/, (route) =>
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    }),
  );
  await page.route("**/api/llm/health", (r) => r.fulfill({ json: { providers: [], spend: { today: 0.12, cap: 1 } } }));
  let n = 0;
  await page.route("**/api/ai/chat", async (r) => {
    bodies.push(r.request().postDataJSON());
    if (answers === "hang") return new Promise(() => undefined);
    const events = answers[Math.min(n++, answers.length - 1)];
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse(events) });
  });
  await openApp(page);
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page) => page.getByTestId("ai-panel");

test.describe("AI panel", () => {
  test("a question on the command line shows the tool call, the cited answer and the model line", async ({ page }) => {
    await setup(page);
    await run(page, "AI what is AAPL trading at");
    await expect(panel(page).getByTestId("ai-tool")).toContainText("[T1] quote");
    await expect(panel(page).getByTestId("ai-tool")).toContainText("yahoo:test");
    await expect(panel(page).getByTestId("ai-tool")).toContainText("OK");
    await expect(panel(page).getByTestId("ai-answer")).toContainText("AAPL is at 343.46 [T1].");
    await expect(panel(page).getByTestId("ai-footer")).toContainText("AI · deepseek/deepseek-v4-pro · 10:00:00Z · MODEL OUTPUT, NOT DATA · US$0.0012");
    await expect(panel(page)).toContainText("US$0.12 OF US$1.00 TODAY");
    await expect(panel(page).getByTestId("ai-label")).toHaveCount(0);
    await expect.poll(() => bodies[0]).toMatchObject({ question: "what is AAPL trading at", model: "deepseek/deepseek-v4-pro", provider: "openrouter", history: [] });
  });

  test("an answer without tool data says UNGROUNDED, and invented numbers are listed", async ({ page }) => {
    await setup(page, [[START, { type: "token", text: "It is 999.99." }, { type: "done", answer: "It is 999.99.", grounded: false, label: "UNGROUNDED", unsourced: [], tool_calls: 0, cost: 0, stopped: null }],
                       [START, { type: "tool_call", id: "T1", name: "quote", args: {} }, { type: "tool_result", id: "T1", name: "quote", ok: true, empty: false, source: "s", age_s: 1, stale: false, bytes: 1, summary: "" },
                        { type: "done", answer: "It is 5.55 and 6.66.", grounded: true, label: null, unsourced: ["5.55", "6.66"], tool_calls: 1, cost: 0, stopped: null }]]);
    await run(page, "AI anything");
    await expect(panel(page).getByTestId("ai-label")).toContainText("UNGROUNDED");
    await panel(page).click();
    await expect(async () => {
      await page.keyboard.press("i");
      await page.keyboard.type("again");
      await page.keyboard.press("Enter");
      await expect(panel(page).getByTestId("ai-unsourced")).toContainText("5.55 6.66", { timeout: 1500 });
    }).toPass();
  });

  test("failed and stale tool results are shown plainly, with the stop notice", async ({ page }) => {
    await setup(page, [[START,
      { type: "tool_call", id: "T1", name: "news", args: { symbol: "ZZZ" } },
      { type: "tool_result", id: "T1", name: "news", ok: false, empty: false, source: null, age_s: null, stale: false, bytes: 9, summary: "HTTP 500: NO DATA" },
      { type: "tool_call", id: "T2", name: "quote", args: { symbols: "AAPL" } },
      { type: "tool_result", id: "T2", name: "quote", ok: true, empty: false, source: "yahoo", age_s: 300, stale: true, bytes: 9, summary: "" },
      { type: "notice", text: "STOPPED: 3 FAILED OR EMPTY TOOL CALLS IN A ROW" },
      { type: "done", answer: "Could not get data.", grounded: true, label: null, unsourced: [], tool_calls: 2, cost: 0, stopped: "x" }]]);
    await run(page, "AI news on ZZZ");
    const tools = panel(page).getByTestId("ai-tool");
    await expect(tools.nth(0)).toContainText("FAILED · HTTP 500: NO DATA");
    await expect(tools.nth(1)).toContainText("STALE");
    await expect(panel(page)).toContainText("STOPPED: 3 FAILED OR EMPTY TOOL CALLS IN A ROW");
  });

  test("no key: the error says KEY REQUIRED and names where to set it", async ({ page }) => {
    await setup(page, [[START, { type: "error", kind: "key_required", text: "KEY REQUIRED: set OPENROUTER in APIKEYS" }]]);
    await run(page, "AI hello");
    await expect(panel(page).getByTestId("ai-error")).toContainText("KEY REQUIRED: set OPENROUTER in APIKEYS");
  });

  test("I types a follow-up that carries the earlier turn as history; X clears", async ({ page }) => {
    await setup(page);
    await run(page, "AI first question");
    await expect(panel(page).getByTestId("ai-footer")).toHaveCount(1);
    await expect(async () => {
      await page.keyboard.press("Escape");
      await page.keyboard.press("i");
      await page.keyboard.type("second");
      await page.keyboard.press("Enter");
      await expect(panel(page).getByTestId("ai-footer")).toHaveCount(2, { timeout: 1500 });
    }).toPass();
    expect(bodies[1].question).toBe("second");
    expect(bodies[1].history).toEqual([{ role: "user", content: "first question" }, { role: "assistant", content: "AAPL is at 343.46 [T1]." }]);
    await page.keyboard.press("Escape");
    await expect(async () => {
      await page.keyboard.press("x");
      await expect(panel(page).getByTestId("ai-turn")).toHaveCount(0, { timeout: 1000 });
    }).toPass();
  });

  test("Esc cancels an answer that is still running", async ({ page }) => {
    await setup(page, "hang");
    await run(page, "AI slow one");
    await expect(panel(page).getByTestId("ai-turn")).toHaveCount(1);
    await expect(async () => {
      await page.keyboard.press("Escape");
      await expect(panel(page)).toContainText("CANCELLED (ESC)", { timeout: 1000 });
    }).toPass();
    await expect(panel(page).getByTestId("ai-label")).toContainText("INCOMPLETE");
  });

  test("SETTINGS AI MODEL changes the model the next question uses", async ({ page }) => {
    await setup(page);
    await run(page, "SETTINGS AI MODEL deepseek/deepseek-v4-flash");
    await run(page, "AI hello");
    await expect.poll(() => bodies[0]?.model).toBe("deepseek/deepseek-v4-flash");
  });
});
