/** Watchlists (`WL`): stored in SQLite by the backend. Actions report through the status line. */
import { api, type ApiError, type WatchlistInfo } from "../net/api";
import { createStore } from "../state/store";
import { fail, info } from "./status";

export { parseWl, type WlAction } from "./watchlistArgs";

/** Saved list names for autocomplete and the WL index. null until first fetched. */
export const watchlistList = createStore<WatchlistInfo[] | null>(null);
/** Bumped after every change so open WL panels refetch. */
export const watchlistVersion = createStore(0);
let fetchedAt = 0;

export async function refreshWatchlists(maxAgeMs = 0): Promise<WatchlistInfo[]> {
  const cur = watchlistList.get();
  if (cur && performance.now() - fetchedAt < maxAgeMs) return cur;
  const { watchlists } = await api.watchlists();
  fetchedAt = performance.now();
  watchlistList.set(() => watchlists);
  return watchlists;
}

const errText = (e: unknown) => (e as ApiError).message ?? String(e);

function changed(): void {
  watchlistVersion.set((n) => n + 1);
  void refreshWatchlists().catch(() => {});
}

/** `note` replaces the default status message (the WL panel adds its undo hint). */
export async function editWatchlist(name: string, add: string[], remove: string[], note?: string): Promise<boolean> {
  try {
    const wl = await api.editWatchlist(name, add.length ? { add, remove } : { remove });
    const n = `(${wl.symbols.length} SYMBOLS)`;
    info(note ?? (add.length ? `WL ${name}: ADDED ${add.length} ${n}` : `REMOVED ${remove.join(" ")} FROM ${name} ${n}`));
  } catch (e) {
    changed();
    return fail(`WL ${name} NOT CHANGED: ${errText(e)}`);
  }
  changed();
  return true;
}

/** Replaces the whole list (undo of a removal restores the exact order). */
export async function putWatchlist(name: string, symbols: string[]): Promise<boolean> {
  try {
    await api.putWatchlist(name, symbols);
  } catch (e) {
    return fail(`WL ${name} NOT SAVED: ${errText(e)}`);
  } finally {
    changed();
  }
  info(`WL ${name}: RESTORED (${symbols.length} SYMBOLS)`);
  return true;
}

export async function deleteWatchlist(name: string): Promise<boolean> {
  try {
    await api.deleteWatchlist(name);
  } catch (e) {
    return fail((e as ApiError).status === 404 ? `NO WATCHLIST ${name}` : `WL ${name} NOT DELETED: ${errText(e)}`);
  }
  info(`WATCHLIST ${name} DELETED`);
  changed();
  return true;
}
