import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/** IND: indicator library panel (search, formula box with error position, presets through the mocked API). */
const cmd = async (page: Page, text: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
};

test.beforeEach(async ({ page }) => {
  await openApp(page);
});

test("search finds RSI and shows its plain-English line", async ({ page }) => {
  await cmd(page, "IND");
  const search = page.getByTestId("ind-search");
  await expect(search).toBeVisible();
  await search.fill("rsi");
  const row = page.locator('.ind-row[data-id="RSI"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText("Relative Strength Index");
  await expect(row).toContainText("0 to 100");
  await search.fill("zzzz");
  await expect(page.getByTestId("ind-list")).toContainText("NO INDICATOR MATCHES");
});

test("Enter with no chart open says to open one", async ({ page }) => {
  await cmd(page, "IND");
  const search = page.getByTestId("ind-search");
  await search.fill("rsi");
  await search.press("Enter");
  await expect(page.getByTestId("ind-msg")).toHaveText("OPEN A CHART (GP) FIRST");
  await expect(page.getByTestId("ind-picked")).toContainText("RSI");
});

test("formula box: error with position for a bad formula, OK for a good one", async ({ page }) => {
  await cmd(page, "IND");
  const search = page.getByTestId("ind-search");
  await expect(search).toBeVisible();
  await search.press("Enter"); // Enter on the formula row opens the formula box
  const box = page.getByTestId("ind-formula");
  await expect(box).toBeVisible();
  await box.fill("EMA(close,");
  const status = page.getByTestId("ind-formula-status");
  await expect(status).toContainText("ERR: EXPECTED EXPRESSION AT 11");
  await box.fill("EMA(close,12)-EMA(close,26)");
  await expect(status).toHaveText("OK");
  await box.fill("FOO(close)");
  await expect(status).toContainText("UNKNOWN FUNCTION FOO AT 1");
  await box.fill("EMA(close,12)-EMA(close,26)");
  await box.press("Enter");
  await expect(page.getByTestId("ind-msg")).toHaveText("OPEN A CHART (GP) FIRST");
  await expect(page.getByTestId("ind-picked")).toContainText("EMA(close,12)-EMA(close,26)");
});

test("presets: save sends the picked list, load lists and applies it", async ({ page }) => {
  const saved: { name: string; body: unknown }[] = [];
  const store: Record<string, unknown> = {};
  await page.route("**/api/indicator-presets**", async (route) => {
    const req = route.request();
    const name = decodeURIComponent(new URL(req.url()).pathname.split("/api/indicator-presets/")[1] ?? "");
    if (req.method() === "PUT") {
      const body = req.postDataJSON() as { items: unknown[] };
      saved.push({ name, body });
      store[name] = { name, items: body.items, updated_at: 1 };
      return route.fulfill({ json: store[name] });
    }
    if (req.method() === "DELETE") {
      delete store[name];
      return route.fulfill({ json: { deleted: name } });
    }
    return route.fulfill({ json: { presets: Object.values(store) } });
  });
  await cmd(page, "IND");
  const search = page.getByTestId("ind-search");
  await search.fill("macd");
  await search.press("Enter");
  await search.fill("rsi 21");
  await search.press("Enter");
  await expect(page.getByTestId("ind-picked")).toContainText("MACD, RSI(21)");

  await search.press("Escape"); // clear the query
  await search.press("Escape"); // leave the box so panel keys work
  await expect(async () => {
    await page.keyboard.press("s");
    await expect(page.getByTestId("ind-preset-name")).toBeVisible({ timeout: 300 });
  }).toPass();
  await page.getByTestId("ind-preset-name").fill("My set");
  await page.getByTestId("ind-preset-name").press("Enter");
  await expect(page.getByTestId("ind-msg")).toHaveText("SAVED PRESET My set (2)");
  expect(saved).toHaveLength(1);
  expect(saved[0].name).toBe("My set");
  expect(saved[0].body).toEqual({ items: [{ id: "MACD", params: [], label: "" }, { id: "RSI", params: [21], label: "" }] });

  await expect(async () => {
    await page.keyboard.press("Escape");
    await page.keyboard.press("l");
    await expect(page.getByTestId("ind-list")).toContainText("My set", { timeout: 300 });
  }).toPass();
  await expect(page.getByTestId("ind-list")).toContainText("MACD, RSI(21)");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("ind-msg")).toHaveText("OPEN A CHART (GP) FIRST"); // nothing answered the bus
});
