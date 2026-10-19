/**
 * Debounced saver for GP drawings (pure: no React, no network; the caller supplies `save`).
 * It remembers which symbol the loaded list belongs to, so a save always goes to that symbol, never to a
 * symbol captured by an old render's closure (a panel keeps its GP instance when the security changes).
 */
import type { Drawing } from "./drawings";

export interface DrawSaver {
  /** The symbol changed: its list is loading, nothing may be saved until `loaded`. */
  reset(): void;
  /** The list for `symbol` arrived from the server. */
  loaded(symbol: string): void;
  /** The user changed the list: save it (to the symbol it was loaded for) after the delay. */
  change(list: Drawing[]): void;
  /** Save a pending change now (symbol switch, unmount). */
  flush(): void;
}

export function createDrawSaver(
  save: (symbol: string, list: Drawing[]) => Promise<unknown>,
  onNote: (note: string | null) => void,
  delayMs = 400,
): DrawSaver {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let dirty = false;
  let loadedFor: string | null = null;
  let latest: Drawing[] = [];
  const stop = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  const flush = () => {
    stop();
    if (!dirty || loadedFor === null) return;
    dirty = false;
    save(loadedFor, latest)
      .then(() => onNote(null))
      .catch((e: { message?: string }) => onNote(`DRAWINGS NOT SAVED: ${e?.message ?? "ERROR"}`));
  };
  return {
    reset() {
      stop();
      dirty = false;
      loadedFor = null;
      latest = [];
    },
    loaded(symbol) {
      loadedFor = symbol;
      dirty = false; // the list on screen is now the server's: an edit made while it loaded is gone, never saved over it
    },
    change(list) {
      latest = list;
      dirty = true;
      stop();
      timer = setTimeout(flush, delayMs);
    },
    flush,
  };
}
