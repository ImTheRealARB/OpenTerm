/** The synced settings document (SETTINGS). Uncached (`send`). */
import { send } from "./core";
import type { SettingsDoc } from "./types";

export const settingsApi = {
  get: () => send<SettingsDoc>("GET", "/api/settings"),
  /** `fieldTimes` asks for the per-field merge (settings/schema.ts); the answer is the merged document now stored. */
  put: (settings: unknown, fieldTimes: Record<string, number>) =>
    send<SettingsDoc & { settings: Record<string, unknown> }>("PUT", "/api/settings", { version: 1, settings, field_times: fieldTimes }),
};
