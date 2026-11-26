/** Watchlists (`WL`): stored in SQLite by the backend. Actions report through the status line. */
import type { ApiError } from "../net/core";
import type { WatchlistInfo } from "../net/types";
import { workspaceApi } from "../net/workspaceApi";
import { createStore } from "../state/store";
import { fail, info } from "./status";
import { errMessage } from "../net/errText";
import { applyMetaChange, EMPTY_META, type MetaChange } from "../functions/wlFlags";

export { parseWl, type WlAction } from "./watchlistArgs";

/** Saved list names for autocomplete and the WL index. null until first fetched. */
export const watchlistList = createStore<WatchlistInfo[] | null>(null);
/** Bumped after every change so open WL panels refetch. */
export const watchlistVersion = createStore(0);
let fetchedAt = 0;

export async function refreshWatchlists(maxAgeMs = 0): Promise<WatchlistInfo[]> {
  const cur = watchlistList.get();
  if (cur && performance.now() - fetchedAt < maxAgeMs) return cur;
  const { watchlists } = await workspaceApi.watchlists();
  fetchedAt = performance.now();
  watchlistList.set(() => watchlists);
  return watchlists;
}


function changed(): void {
  watchlistVersion.set((n) => n + 1);
  // Ignored on purpose: only the list NAMES for autocomplete; the change itself already succeeded and said so.
  void refreshWatchlists().catch(() => {});
}

/** `note` replaces the default status message (the WL panel adds its undo hint). */
export async function editWatchlist(name: string, add: string[], remove: string[], note?: string): Promise<boolean> {
  try {
    const wl = await workspaceApi.editWatchlist(name, add.length ? { add, remove } : { remove });
    const n = `(${wl.symbols.length} SYMBOLS)`;
    info(note ?? (add.length ? `WL ${name}: ADDED ${add.length} ${n}` : `REMOVED ${remove.join(" ")} FROM ${name} ${n}`));
  } catch (e) {
    changed();
    return fail(`WL ${name} NOT CHANGED: ${errMessage(e)}`);
  }
  changed();
  return true;
}

/**
 * Phase 22: one flag or section edit. The server stores the whole document each time, so read the current one, apply the
 * edit (`wlFlags.applyMetaChange`) and send it back; then every open view of the list refetches.
 */
export async function editWatchlistMeta(name: string, change: MetaChange): Promise<boolean> {
  try {
    const wl = await workspaceApi.watchlist(name);
    await workspaceApi.putWatchlistMeta(name, applyMetaChange(wl.meta ?? EMPTY_META, change));
    info(change.kind === "flag" ? `WL ${name}: ${change.symbol} ${change.color ?? "UNFLAGGED"}` : `WL ${name}: ${change.title ? `SECTION "${change.title}" ABOVE` : "NO SECTION ABOVE"} ${change.before}`);
  } catch (e) {
    return fail(`WL ${name} NOT CHANGED: ${errMessage(e)}`);
  } finally {
    changed();
  }
  return true;
}

/** Replaces the whole list (undo of a removal restores the exact order). */
export async function putWatchlist(name: string, symbols: string[]): Promise<boolean> {
  try {
    await workspaceApi.putWatchlist(name, symbols);
  } catch (e) {
    return fail(`WL ${name} NOT SAVED: ${errMessage(e)}`);
  } finally {
    changed();
  }
  info(`WL ${name}: RESTORED (${symbols.length} SYMBOLS)`);
  return true;
}

export async function deleteWatchlist(name: string): Promise<boolean> {
  try {
    await workspaceApi.deleteWatchlist(name);
  } catch (e) {
    return fail((e as ApiError).status === 404 ? `NO WATCHLIST ${name}` : `WL ${name} NOT DELETED: ${errMessage(e)}`);
  }
  info(`WATCHLIST ${name} DELETED`);
  changed();
  return true;
}
