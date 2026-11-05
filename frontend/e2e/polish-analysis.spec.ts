import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";
import { env, quote } from "./p19util";

/**
 * Step C polish for GP, FA, PORT and BT: every "nothing to show" state uses the shared PanelNote
 * (`[data-kind=...]`) and an empty state says what to do next. Mocked routes only (no network).
 * Each test runs in both shells (terminal and GUI): the notes look the same in both.
 */

type Mode = "terminal" | "gui";
const MODES: Mode[] = ["terminal", "gui"];

/** Mocks the WebSocket (ping/pong only) and the quote feed, then opens the app in the given shell. */
async function setup(page: Page, mode: Mode) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i))])) } });
  });
  await openApp(page, { mode });
  return { errors };
}

const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);

/** Runs a command the way the user would in each shell: the command line in GUI mode, Ctrl+K in the terminal shell. */
async function run(page: Page, mode: Mode, text: string) {
  if (mode === "gui") {
    await page.locator("#cmdline").fill(text);
    await page.locator("#cmdline").press("Enter");
    return;
  }
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
}

for (const mode of MODES) {
  test(`PORT with no positions shows an empty note that names the next step (${mode})`, async ({ page }) => {
    const { errors } = await setup(page, mode);
    // A portfolio that exists but holds nothing.
    await page.route("**/api/portfolios/EMPTYBOOK", (r) => r.fulfill({ json: { name: "EMPTYBOOK", base: "USD", positions: [], updated_at: Date.now() / 1000 } }));
    await run(page, mode, "PORT EMPTYBOOK");
    const note = panel(page).locator('.pnote[data-kind="empty"]');
    await expect(note).toBeVisible();
    await expect(note).toContainText("NO POSITIONS IN EMPTYBOOK");
    // The hint is the command to type, plus the key.
    await expect(note.locator(".pnote-hint")).toContainText("PORT EMPTYBOOK ADD AAPL 10 150");
    // The summary strip keeps its test id and text with nothing in it.
    await expect(panel(page).getByTestId("port-summary")).toContainText("TOTAL USD MKT VAL");
    expect(errors).toEqual([]);
  });

  test(`PORT of a name that does not exist yet says how to create it (${mode})`, async ({ page }) => {
    await setup(page, mode);
    await page.route("**/api/portfolios/GHOST", (r) => r.fulfill({ status: 404, json: { error: "NO PORTFOLIO GHOST", kind: "not_found" } }));
    await run(page, mode, "PORT GHOST");
    const note = panel(page).locator('.pnote[data-kind="empty"]');
    await expect(note).toContainText("NO PORTFOLIO GHOST");
    await expect(note.locator(".pnote-hint")).toContainText("PORT GHOST ADD AAPL 10 150");
  });

  test(`BT RUNS with no stored runs shows an empty note with the command that starts one (${mode})`, async ({ page }) => {
    const { errors } = await setup(page, mode);
    await page.route("**/api/bt/runs", (r) => r.fulfill({ json: { runs: [] } }));
    await run(page, mode, "BT RUNS");
    const note = panel(page).locator('.pnote[data-kind="empty"]');
    await expect(note).toContainText("NO RUNS YET");
    await expect(note.locator(".pnote-hint")).toContainText("BT AAPL SMA20>SMA50 1D 5Y");
    expect(errors).toEqual([]);
  });

  test(`FA with a failed fetch shows an error note with the reason and a retry hint (${mode})`, async ({ page }) => {
    await setup(page, mode);
    await page.route("**/api/fa?**", (r) => r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "sec: unavailable (timeout)" } }));
    await run(page, mode, "AAPL FA");
    const note = panel(page).locator('.pnote[data-kind="error"]');
    // The error keeps its source and reason: never a silent blank.
    await expect(note).toContainText("PROVIDER DOWN");
    await expect(note).toContainText("sec: unavailable (timeout)");
    // Terminal shows the key; GUI drops "F5" key legends because every panel's toolbar has a Refresh button.
    if (mode === "gui") {
      await expect(note).not.toContainText("F5");
      await expect(panel(page).locator(".pt .pt-b", { hasText: "Refresh" })).toBeVisible();
    }
    else await expect(note.locator(".pnote-hint")).toContainText("F5 TO RETRY");
  });
}
