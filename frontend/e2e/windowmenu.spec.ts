import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

const cmd = async (page: Page, text: string, key = "Enter") => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press(key);
};
const panel = (page: Page, id: number) => page.locator(`[data-panel="${id}"]`);
const menu = (page: Page) => page.getByTestId("window-menu");

test.beforeEach(async ({ page }) => {
  await openApp(page);
});

test("window menu: RECENT jumps back, RELATED keeps the security, OPTIONS splits (keyboard only)", async ({ page }) => {
  await cmd(page, "HELP");
  await cmd(page, "MSFT DES");
  await expect(panel(page, 1).locator(".ph")).toContainText("MSFT | DES");
  await expect(panel(page, 1).locator(".ph")).toContainText("RECENT ▾");

  // RECENT: newest first, so item 2 is HELP.
  await page.keyboard.press("Alt+m");
  await expect(menu(page)).toContainText("MSFT DES (CURRENT)");
  await page.keyboard.press("2");
  await expect(menu(page)).toHaveCount(0);
  await expect(panel(page, 1)).toContainText("FUNCTIONS");

  // RELATED on a security view offers GP for the same symbol.
  await page.keyboard.press("Alt+m");
  await page.keyboard.press("1"); // back to MSFT DES
  await expect(panel(page, 1).locator(".ph")).toContainText("MSFT | DES");
  await page.keyboard.press("Alt+m");
  await page.keyboard.press("ArrowRight");
  await expect(menu(page)).toContainText("GP");
  await expect(menu(page).locator(".on")).toContainText("GP");
  await page.keyboard.press("Enter");
  await expect(panel(page, 1).locator(".ph")).toContainText("MSFT | GP");

  // OPTIONS: 2) SPLIT VERTICAL opens panel 2; Esc closes an open menu.
  await page.keyboard.press("Alt+m");
  await page.keyboard.press("ArrowLeft");
  await expect(menu(page)).toContainText("SPLIT VERTICAL");
  await page.keyboard.press("2");
  await expect(panel(page, 2)).toBeVisible();
  await page.keyboard.press("Alt+m");
  await page.keyboard.press("Escape");
  await expect(menu(page)).toHaveCount(0);
});

test("window menu opens with the mouse on the title bar", async ({ page }) => {
  await cmd(page, "WEI");
  await panel(page, 1).locator(".wm-t", { hasText: "OPTIONS" }).click();
  await expect(menu(page)).toContainText("MAXIMIZE / RESTORE");
});
