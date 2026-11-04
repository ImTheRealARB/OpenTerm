/** Indicator presets (IND panel only), kept out of api.ts so the startup bundle does not carry them. */
import { send, type IndicatorPreset, type PresetItem } from "./api";

export const presetsApi = {
  list: () => send<{ presets: IndicatorPreset[] }>("GET", "/api/indicator-presets"),
  put: (name: string, items: PresetItem[]) => send<IndicatorPreset>("PUT", `/api/indicator-presets/${encodeURIComponent(name)}`, { items }),
  remove: (name: string) => send<{ deleted: string }>("DELETE", `/api/indicator-presets/${encodeURIComponent(name)}`),
};
