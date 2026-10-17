import { api } from "../net/api";
import { loadJSON, saveJSON } from "../state/store";

/** Pre-phase-4 history lived in localStorage. It is uploaded once, then removed. */
const LEGACY_KEY = "openterm.cmdHistory";
const RECENT_KEY = "openterm.recentSecurities";
const MAX = 500;
const FLUSH_MS = 500;

/**
 * Command history (Up/Down). Stored in SQLite through `/api/cmdhistory`; this is the in-memory copy.
 * Writes are batched off the command path, so running a command never waits on the network.
 * If the backend is down, history keeps working in memory and is uploaded on the next flush.
 */
export class CommandHistory {
  private items: string[] = [];
  private pending: string[] = [];
  private cursor = -1;
  private timer = 0;
  private recent: string[] = loadJSON<string[]>(RECENT_KEY, []);

  /** Loads the stored history. Commands typed before it arrives stay the newest entries. */
  async sync(): Promise<void> {
    const { items } = await api.cmdHistory();
    const legacy = loadJSON<string[]>(LEGACY_KEY, []);
    let stored = items;
    if (!items.length && legacy.length) {
      await api.pushCmdHistory(legacy);
      stored = legacy.slice(-MAX);
    }
    try {
      localStorage.removeItem(LEGACY_KEY);
    } catch {
      /* storage unavailable */
    }
    this.items = [...stored, ...this.items].slice(-MAX);
    this.cursor = -1;
  }

  push(cmd: string): void {
    if (this.items[this.items.length - 1] === cmd) return;
    this.items.push(cmd);
    if (this.items.length > MAX) this.items.splice(0, this.items.length - MAX);
    this.cursor = -1;
    this.pending.push(cmd);
    clearTimeout(this.timer);
    this.timer = window.setTimeout(() => void this.flush(), FLUSH_MS);
  }

  async flush(): Promise<void> {
    if (!this.pending.length) return;
    const batch = this.pending;
    this.pending = [];
    try {
      await api.pushCmdHistory(batch);
    } catch {
      this.pending = [...batch, ...this.pending].slice(-MAX); // retried with the next command
    }
  }

  /** Last-chance upload when the page goes away. */
  flushOnExit(): void {
    if (!this.pending.length) return;
    const body = new Blob([JSON.stringify({ cmds: this.pending })], { type: "application/json" });
    if (navigator.sendBeacon?.("/api/cmdhistory", body)) this.pending = [];
  }

  /** dir -1 = older, +1 = newer. Returns null when past the newest entry. */
  step(dir: -1 | 1): string | null {
    if (!this.items.length) return null;
    if (this.cursor === -1) {
      if (dir === 1) return null;
      this.cursor = this.items.length - 1;
    } else {
      this.cursor += dir;
    }
    if (this.cursor >= this.items.length) {
      this.cursor = -1;
      return null;
    }
    if (this.cursor < 0) this.cursor = 0;
    return this.items[this.cursor];
  }

  resetCursor(): void {
    this.cursor = -1;
  }

  /** Autocomplete hint cache, not history: stays in localStorage so it is ready on the first keystroke. */
  addRecentSecurity(symbol: string): void {
    this.recent = [symbol, ...this.recent.filter((s) => s !== symbol)].slice(0, 50);
    saveJSON(RECENT_KEY, this.recent);
  }

  recentSecurities(): string[] {
    return this.recent;
  }
}

export const history = new CommandHistory();
