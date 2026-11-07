/** What the user keeps on the server between sessions: saved layouts, watchlists and the command history. All uncached (`send`). */
import { send } from "./core";
import type { LayoutInfo, Watchlist, WatchlistInfo } from "./types";

export const workspaceApi = {
  layouts: () => send<{ layouts: LayoutInfo[] }>("GET", "/api/layouts"),
  layout: (name: string) => send<{ name: string; state: unknown; updated_at: number }>("GET", `/api/layouts/${encodeURIComponent(name)}`),
  saveLayout: (name: string, state: unknown) =>
    send<{ name: string; updated_at: number }>("PUT", `/api/layouts/${encodeURIComponent(name)}`, { state }),
  deleteLayout: (name: string) => send<{ deleted: string }>("DELETE", `/api/layouts/${encodeURIComponent(name)}`),
  watchlists: () => send<{ watchlists: WatchlistInfo[] }>("GET", "/api/watchlists"),
  watchlist: (name: string) => send<Watchlist>("GET", `/api/watchlists/${encodeURIComponent(name)}`),
  putWatchlist: (name: string, symbols: string[]) => send<Watchlist>("PUT", `/api/watchlists/${encodeURIComponent(name)}`, { symbols }),
  editWatchlist: (name: string, change: { add?: string[]; remove?: string[] }) =>
    send<Watchlist>("PATCH", `/api/watchlists/${encodeURIComponent(name)}`, change),
  deleteWatchlist: (name: string) => send<{ deleted: string }>("DELETE", `/api/watchlists/${encodeURIComponent(name)}`),
  cmdHistory: () => send<{ items: string[] }>("GET", "/api/cmdhistory"),
  pushCmdHistory: (cmds: string[]) => send<{ added: number }>("POST", "/api/cmdhistory", { cmds }),
};
