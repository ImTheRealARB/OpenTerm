import { expect, test, type Page } from "@playwright/test";
import { alertDirection, fmtAlertPrice, roundAlertPrice } from "../src/chart/alertPrice";
import { openApp } from "./app";
import { base, bars, env, gauge, N, panel, quote, run } from "./p19util";

// Alert from the chart: key A (crosshair or last price), Shift+A / toolbar button + click, Alt+click. Mocked routes only.

interface Al { id: number; symbol: string; op: string; unit: string; value: number; status: string; created_at: number; triggered_at: null; trigger_price: null }

async function setup(page: Page, mode: "terminal" | "gui" = "terminal") {
  const errors: string[] = [];
  const created: { symbol: string; op: string; unit: string; value: number }[] = [];
  const alerts: Al[] = [];
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
  await page.route("**/api/history?**", (r) => {
    const u = new URL(r.request().url());
    return r.fulfill({ json: env(bars(u.searchParams.get("symbol")!, u.searchParams.get("range") ?? "", u.searchParams.get("interval") ?? "")) });
  });
  await page.route("**/api/alerts**", (r) => {
    const req = r.request();
    const rest = new URL(req.url()).pathname.split("/api/alerts")[1].replace(/^\//, "");
    if (!rest && req.method() === "POST") {
      const body = req.postDataJSON();
      created.push(body);
      const a: Al = { id: alerts.length + 1, ...body, status: "active", created_at: Date.now() / 1000, triggered_at: null, trigger_price: null };
      alerts.push(a);
      return r.fulfill({ json: a });
    }
    if (rest && req.method() === "DELETE") {
      const i = alerts.findIndex((a) => a.id === Number(rest));
      if (i >= 0) alerts.splice(i, 1);
      return r.fulfill({ json: { deleted: Number(rest) } });
    }
    return r.fulfill({ json: { alerts } });
  });
  await openApp(page, { mode });
  return { errors, created, alerts };
}

const last = base(N - 1);
const status = (page: Page) => page.locator(".status, .top-msg, header").filter({ hasText: "ALERT SET" }).first();

test("GP: key A at the crosshair price creates the alert, shows it and draws a line", async ({ page }) => {
  const { errors, created } = await setup(page);
  await run(page, "AAA GP 1Y");
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  const rebuilds = await gauge(page, "chart.rebuilds");
  await page.keyboard.press("x");
  for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("a");
  const want = roundAlertPrice(base(N - 1 - 5))!;
  await expect.poll(() => created.length).toBe(1);
  expect(created[0]).toEqual({ symbol: "AAA", op: alertDirection(want, last), unit: "price", value: Number(fmtAlertPrice(want)) });
  await expect(page.getByText(`ALERT SET: AAA ${created[0].op} ${fmtAlertPrice(want)} (ALRT TO MANAGE)`).first()).toBeVisible();
  await expect.poll(() => gauge(page, "chart.alertLines")).toBe(1);
  // The line is added without rebuilding the chart.
  expect(await gauge(page, "chart.rebuilds")).toBe(rebuilds);
  expect(errors).toEqual([]);
});

test("GP: key A without a crosshair uses the last price", async ({ page }) => {
  const { created } = await setup(page);
  await run(page, "AAA GP 1Y");
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  await page.keyboard.press("a");
  await expect.poll(() => created.length).toBe(1);
  expect(created[0].value).toBe(Number(fmtAlertPrice(roundAlertPrice(last)!)));
  expect(created[0].unit).toBe("price");
});

test("GP: Alt+click on the chart sets an alert at the clicked price", async ({ page }) => {
  const { created } = await setup(page);
  await run(page, "AAA GP 1Y");
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  const box = (await panel(page).locator(".chart").boundingBox())!;
  // Near the top of the plot: above the last price.
  await page.keyboard.down("Alt");
  await page.mouse.click(box.x + box.width / 2, box.y + 30);
  await page.keyboard.up("Alt");
  await expect.poll(() => created.length).toBe(1);
  expect(created[0].op).toBe(">");
  expect(created[0].value).toBeGreaterThan(last);
  await expect.poll(() => gauge(page, "chart.alertLines")).toBe(1);
  // A click without Alt and without arming does nothing.
  await page.mouse.click(box.x + box.width / 2, box.y + 60);
  expect(created).toHaveLength(1);
});

test("GP: Shift+A arms one click, Esc cancels", async ({ page }) => {
  const { created } = await setup(page);
  await run(page, "AAA GP 1Y");
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  const box = (await panel(page).locator(".chart").boundingBox())!;
  await page.keyboard.press("Shift+A");
  await expect(panel(page)).toContainText("CLICK THE CHART TO SET AN ALERT, ESC TO CANCEL");
  await page.keyboard.press("Escape");
  await expect(panel(page)).not.toContainText("CLICK THE CHART TO SET AN ALERT");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height - 160);
  expect(created).toHaveLength(0);
  await page.keyboard.press("Shift+A");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height - 160);
  await expect.poll(() => created.length).toBe(1);
  expect(created[0].op).toBe("<");
  await expect(panel(page)).not.toContainText("CLICK THE CHART TO SET AN ALERT");
});

test("GP: GUI toolbar button arms a click that sets an alert; deleting the alert removes the line", async ({ page }) => {
  const { created, alerts } = await setup(page, "gui");
  await run(page, "AAA GP 1Y");
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  const box = (await panel(page).locator(".chart").boundingBox())!;
  await panel(page).getByRole("button", { name: "Price alert" }).click();
  await expect(panel(page)).toContainText("CLICK THE CHART TO SET AN ALERT, ESC TO CANCEL");
  await page.mouse.click(box.x + box.width / 2, box.y + 30);
  await expect.poll(() => created.length).toBe(1);
  await expect.poll(() => gauge(page, "chart.alertLines")).toBe(1);
  // ALRT DEL removes the line again.
  await run(page, `ALRT DEL ${alerts[0].id}`);
  await expect.poll(() => gauge(page, "chart.alertLines")).toBe(0);
});
