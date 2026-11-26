/**
 * `LINK A|B|C|D|OFF` (Phase 22): puts a panel in a colour group or takes it out. Bare `LINK` says which group the panel is
 * in. A lazy chunk (execute.ts loads it on first use), so it costs nothing at startup.
 */
import { isLinkGroup } from "../state/linkGroups";
import { setLink, workspace } from "../state/workspace";
import { fail, info } from "./status";

export function linkCommand(args: string[], id: number): boolean {
  const w = (args[0] ?? "").toUpperCase();
  if (!w) {
    const g = workspace.get().panels[id]?.link;
    info(g ? `PANEL ${id} IS IN LINK GROUP ${g} · LINK OFF TAKES IT OUT` : `PANEL ${id} IS NOT LINKED · LINK A|B|C|D PUTS IT IN A GROUP`);
    return true;
  }
  if (w === "OFF" || w === "NONE") {
    setLink(id, undefined);
    info(`PANEL ${id} UNLINKED`);
    return true;
  }
  if (!isLinkGroup(w)) return fail("LINK A|B|C|D|OFF");
  setLink(id, w);
  info(`PANEL ${id} IN LINK GROUP ${w}: A NEW SECURITY IN ONE PANEL OF THE GROUP LOADS IN THE OTHERS`);
  return true;
}
