import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

const cmd = async (page: Page, text: string, key = "Enter") => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press(key);
};
const panel = (page: Page, id: number) => page.locator(`[data-panel="${id}"]`);

test.beforeEach(async ({ page }) => {
  await openApp(page);
});

test("HELP lists functions", async ({ page }) => {
  await cmd(page, "HELP");
  await expect(panel(page, 1)).toContainText("FUNCTIONS");
  await cmd(page, "HELP GP");
  await expect(panel(page, 1)).toContainText("GP — PRICE CHART");
});

test("security + function, sticky security, unknown function", async ({ page }) => {
  await cmd(page, "aapl fa");
  await expect(panel(page, 1).locator(".ph")).toContainText("AAPL | FA");
  await cmd(page, "WEI");
  await cmd(page, "FIL");
  await expect(panel(page, 1).locator(".ph")).toContainText("AAPL | FIL");
  await cmd(page, "AAPL XYZ");
  await expect(page.locator(".msg.err")).toHaveText("UNKNOWN FUNCTION: XYZ");
});

test("split, target panel, focus by number, close, mouse-free", async ({ page }) => {
  await page.keyboard.press("Control+\\");
  await expect(panel(page, 2)).toBeVisible();
  await cmd(page, "2: MSFT DES");
  await expect(panel(page, 2).locator(".ph")).toContainText("MSFT | DES");
  await cmd(page, "SHORTCUTS", "Shift+Enter");
  await expect(panel(page, 3)).toContainText("SHORTCUTS");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Alt+1");
  await expect(panel(page, 1)).toHaveClass(/focus/);
  await page.keyboard.press("Alt+w");
  await expect(panel(page, 1)).toHaveCount(0);
});

test("history, cheatsheet, HUD, type-to-command", async ({ page }) => {
  await cmd(page, "HELP");
  await page.keyboard.press("Escape");
  await page.keyboard.press("?");
  await expect(page.locator(".overlay")).toContainText("SHORTCUTS");
  await page.keyboard.press("Escape");
  await expect(page.locator(".overlay")).toHaveCount(0);
  await page.keyboard.press("Control+Shift+P");
  await expect(page.locator(".hud")).toContainText("FPS");
  await page.keyboard.type("p");
  await expect(page.locator("#cmdline")).toBeFocused();
  await expect(page.locator("#cmdline")).toHaveValue("p");
  await page.keyboard.press("Control+a");
  await page.keyboard.press("Backspace");
  await page.keyboard.press("ArrowUp");
  await expect(page.locator("#cmdline")).toHaveValue("HELP");
});

test("Tab accepts autocomplete", async ({ page }) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type("shortc");
  await expect(page.locator(".ac")).toContainText("SHORTCUTS");
  await page.keyboard.press("Tab");
  await expect(page.locator("#cmdline")).toHaveValue("SHORTCUTS ");
});
