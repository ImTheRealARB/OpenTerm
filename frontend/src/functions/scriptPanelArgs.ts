/**
 * SCRIPT panel: the pure parts (words after SCRIPT, names, the chart command, the starter text). No React and no request layer,
 * so vitest can load it.
 *
 *   SCRIPT                   the list: your saved scripts and the 20 starter examples
 *   SCRIPT <NAME>            the editor (a name that does not exist yet starts a new script with that name)
 *   SCRIPT NEW [<EXAMPLE>]   the editor with a new script, or with a copy of a starter example
 *   SCRIPT IMPORT            a paste box that converts common chart-script text, then opens the editor
 */

/**
 * What a saved script's name may look like. A mirror of `backend/openterm/idents.py` STORED_NAME_RE (the server stores names in
 * capitals): `test_script_routes.py` reads this line, so change both together.
 */
export const NAME_RE = /^[A-Z0-9][A-Z0-9_.-]{0,31}$/;

/** Words that mean something after SCRIPT, so a script cannot be called by them. */
export const RESERVED = ["NEW", "IMPORT"] as const;

/** The name as the server stores it (capitals), or null when it cannot be a script name. */
export function scriptName(raw: string): string | null {
  const name = raw.trim().toUpperCase();
  return NAME_RE.test(name) && !(RESERVED as readonly string[]).includes(name) ? name : null;
}

export type ScriptMode =
  | { mode: "list" }
  | { mode: "import" }
  | { mode: "new"; example?: string }
  | { mode: "edit"; name: string }
  | { mode: "error"; error: string };

/** Reads the words after SCRIPT. */
export function parseScriptArgs(args: readonly string[]): ScriptMode {
  const first = (args[0] ?? "").toUpperCase();
  if (!first) return { mode: "list" };
  if (first === "IMPORT") return { mode: "import" };
  if (first === "NEW") return args[1] ? { mode: "new", example: args[1].toUpperCase() } : { mode: "new" };
  const name = scriptName(first);
  if (!name) return { mode: "error", error: "SCRIPT NAMES ARE 1-32 OF A-Z 0-9 _ . - : SCRIPT <NAME>" };
  return { mode: "edit", name };
}

/** What the starter text of a brand new script says. The first line is the one-sentence summary every script starts with. */
export const STARTER = `// Describe what this script shows in one sentence.
indicator("My script", overlay=true)
len = input.int(20, "Length", min=1, max=200)
average = ta.sma(close, len)
plot(average, "Average", color=color.orange)
`;

/** The file name an exported script gets. */
export const exportFileName = (name: string) => `${name.toLowerCase()}.ots`;

/** The least that this file needs to know about a panel (a structural subset of `PanelState` in state/workspace.ts). */
export interface PanelLike {
  views: { fn?: string; security?: { symbol: string } }[];
  pos: number;
}

/**
 * The symbol the script is charted on: this panel's own security, else the newest GP chart's security, else AAPL.
 * (Newest = the highest panel number: panels are numbered as they are created.)
 */
export function chartSymbol(panels: Record<number, PanelLike>, panelId: number): string {
  const own = panels[panelId]?.views[panels[panelId].pos]?.security?.symbol;
  if (own) return own;
  const ids = Object.keys(panels).map(Number).sort((a, b) => b - a);
  for (const id of ids) {
    const p = panels[id];
    const v = p.views[p.pos];
    if (v?.fn === "GP" && v.security) return v.security.symbol;
  }
  return "AAPL";
}

/** The command that puts a saved script on a chart (GP reads `SCRIPT=NAME`). */
export const chartCommand = (symbol: string, name: string) => `${symbol} GP SCRIPT=${name}`;
