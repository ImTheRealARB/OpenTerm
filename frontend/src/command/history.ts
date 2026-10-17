import { loadJSON, saveJSON } from "../state/store";

const KEY = "openterm.cmdHistory";
const RECENT_KEY = "openterm.recentSecurities";
const MAX = 500;

/** Command history (Up/Down). Persisted locally; moves to the SQLite API in phase 2. */
export class CommandHistory {
  private items: string[] = loadJSON<string[]>(KEY, []);
  private cursor = -1;
  private recent: string[] = loadJSON<string[]>(RECENT_KEY, []);

  push(cmd: string): void {
    if (this.items[this.items.length - 1] !== cmd) this.items.push(cmd);
    if (this.items.length > MAX) this.items.splice(0, this.items.length - MAX);
    this.cursor = -1;
    saveJSON(KEY, this.items);
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

  addRecentSecurity(symbol: string): void {
    this.recent = [symbol, ...this.recent.filter((s) => s !== symbol)].slice(0, 50);
    saveJSON(RECENT_KEY, this.recent);
  }

  recentSecurities(): string[] {
    return this.recent;
  }
}

export const history = new CommandHistory();
