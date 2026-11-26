/** Phase 28: the option chain recorder (OREC) and the option scan (OSCAN). Both read OpenTerm's own SQLite snapshots. */
import { send } from "./core";
import type { OptionRecStatus, OptionRecSymbol, OptionScanResult } from "./types";

export const optionsRecApi = {
  status: () => send<OptionRecStatus>("GET", "/api/options/recorder"),
  /** `null` turns the recorder off. */
  set: (watchlist: string | null) => send<OptionRecStatus>("PUT", "/api/options/recorder", { watchlist }),
  run: () => send<OptionRecStatus>("POST", "/api/options/recorder/run", {}),
  symbol: (symbol: string) => send<OptionRecSymbol>("GET", `/api/options/recorder/${encodeURIComponent(symbol)}`),
  scan: (universe: string, filter: string) =>
    send<OptionScanResult>("GET", `/api/options/scan?universe=${encodeURIComponent(universe)}&filter=${encodeURIComponent(filter)}`),
};
