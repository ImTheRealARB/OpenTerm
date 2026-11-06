/** The synced settings document (SETTINGS). Uncached (`send`). */
import { send } from "./core";
import type { SettingsDoc } from "./types";

export const settingsApi = {
  get: () => send<SettingsDoc>("GET", "/api/settings"),
  put: (settings: unknown) => send<{ version: number; settings: unknown; updated_at: number }>("PUT", "/api/settings", { version: 1, settings }),
};
