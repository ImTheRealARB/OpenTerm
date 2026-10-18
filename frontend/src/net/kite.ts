import { createStore } from "../state/store";
import { kiteApi, type KiteStatus } from "./api";

/**
 * Kite Connect login state for the status bar and the KITE panel. Fetched once at start and again after a login or logout (no polling).
 * null = not known (or the call failed); the status bar shows nothing for null and for `NO KEY`.
 */
export const kite = createStore<KiteStatus | null>(null);

let inflight: Promise<KiteStatus | null> | null = null;

export function refreshKite(): Promise<KiteStatus | null> {
  inflight ??= kiteApi
    .status()
    .then((s) => {
      kite.set(() => s);
      return s;
    })
    .catch(() => {
      kite.set(() => null);
      return null;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}
