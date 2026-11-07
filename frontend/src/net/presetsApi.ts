/** Indicator presets (IND panel only), kept in its own file so the startup bundle does not carry them. */
import { send } from "./core";
import type { IndicatorPreset, PresetItem } from "./types";

export const presetsApi = {
  list: () => send<{ presets: IndicatorPreset[] }>("GET", "/api/indicator-presets"),
  put: (name: string, items: PresetItem[]) => send<IndicatorPreset>("PUT", `/api/indicator-presets/${encodeURIComponent(name)}`, { items }),
  remove: (name: string) => send<{ deleted: string }>("DELETE", `/api/indicator-presets/${encodeURIComponent(name)}`),
};
