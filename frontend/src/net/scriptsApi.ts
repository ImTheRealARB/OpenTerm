/**
 * OpenTerm Script storage (SCRIPT panel): the user's saved scripts and the read-only starter examples.
 * The server only stores text. Checking and running a script happens in the browser (`script/` engine).
 * Types live here (type-only exports are erased at build time, so a pure helper may import them without pulling in the request layer).
 */
import { send } from "./core";

/** One row of the saved list: the title is read from the script's `indicator("...")` line (empty when there is none). */
export interface ScriptCard {
  name: string;
  title: string;
  updated_at: number;
}

/** A saved script with its text. */
export interface ScriptRec extends ScriptCard {
  source: string;
  created_at: number;
}

/** One of the 20 starter scripts shipped with OpenTerm. `about` is the one-sentence comment the file starts with. */
export interface ScriptExample {
  name: string;
  title: string;
  about: string;
  source: string;
}

/**
 * A live script alert (`ALRT AAPL SCRIPT=NAME [COND="title"]`): stored on the server, run by the browser while OpenTerm is open.
 * `cond` = the title of one of the script's `alertcondition(...)` calls, or null = fire on the script's own `alert(...)` calls.
 */
export interface ScriptAlert {
  id: number;
  symbol: string;
  script: string;
  cond: string | null;
  created_at: number;
}

export const scriptsApi = {
  list: () => send<{ scripts: ScriptCard[] }>("GET", "/api/scripts"),
  examples: () => send<{ examples: ScriptExample[] }>("GET", "/api/scripts/examples"),
  get: (name: string) => send<ScriptRec>("GET", `/api/scripts/${encodeURIComponent(name)}`),
  /** Creates or replaces. The name is stored in capitals. */
  put: (name: string, source: string) => send<ScriptCard>("PUT", `/api/scripts/${encodeURIComponent(name)}`, { source }),
  remove: (name: string) => send<{ deleted: string }>("DELETE", `/api/scripts/${encodeURIComponent(name)}`),
  alerts: () => send<{ alerts: ScriptAlert[] }>("GET", "/api/scripts/alerts"),
  addAlert: (a: { symbol: string; script: string; cond: string | null }) => send<ScriptAlert>("POST", "/api/scripts/alerts", a),
  removeAlert: (id: number) => send<{ deleted: number }>("DELETE", `/api/scripts/alerts/${id}`),
};
