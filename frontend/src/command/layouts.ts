/** Named layouts (`LAYOUT SAVE|LOAD|DEL name`, Ctrl+S / Ctrl+O), stored in SQLite by the backend. */
import { isFunction } from "../functions/registry";
import type { ApiError } from "../net/core";
import type { LayoutInfo } from "../net/types";
import { workspaceApi } from "../net/workspaceApi";
import { afterPaint, series } from "../perf/metrics";
import { LAYOUT_NAME_RE, parseLayout, snapshot } from "../state/layoutState";
import { createStore } from "../state/store";
import { applyLayout, setLayoutName, workspace } from "../state/workspace";
import { fail, info } from "./status";
import { errMessage } from "../net/errText";

/** Saved layouts for autocomplete and the LAYOUT panel. null until first fetched. */
export const layoutList = createStore<LayoutInfo[] | null>(null);
let fetchedAt = 0;

export async function refreshLayouts(maxAgeMs = 0): Promise<LayoutInfo[]> {
  const cur = layoutList.get();
  if (cur && performance.now() - fetchedAt < maxAgeMs) return cur;
  const { layouts } = await workspaceApi.layouts();
  fetchedAt = performance.now();
  layoutList.set(() => layouts);
  return layouts;
}


export function normName(raw: string | undefined): string | null {
  const name = (raw ?? "").trim().toUpperCase();
  return LAYOUT_NAME_RE.test(name) ? name : null;
}

export async function saveLayout(raw: string): Promise<boolean> {
  const name = normName(raw);
  if (!name) return fail("LAYOUT NAME: 1-32 OF A-Z 0-9 _ . -");
  const snap = snapshot(workspace.get());
  try {
    await workspaceApi.saveLayout(name, snap);
  } catch (e) {
    return fail(`LAYOUT ${name} NOT SAVED: ${errMessage(e)}`);
  }
  setLayoutName(name);
  info(`LAYOUT ${name} SAVED (${Object.keys(snap.panels).length} PANELS)`);
  // Ignored on purpose: this only refreshes the layout NAMES used for autocomplete, after the save/delete above already
  // succeeded and said so. A real use of the list (typing LAYOUT ...) refetches and reports a failure then.
  void refreshLayouts().catch(() => {});
  return true;
}

export async function loadLayout(raw: string): Promise<boolean> {
  const name = normName(raw);
  if (!name) return fail("LAYOUT NAME: 1-32 OF A-Z 0-9 _ . -");
  const t0 = performance.now();
  let state: unknown;
  try {
    state = (await workspaceApi.layout(name)).state;
  } catch (e) {
    return fail((e as ApiError).status === 404 ? `NO LAYOUT ${name}` : `LAYOUT ${name} NOT LOADED: ${errMessage(e)}`);
  }
  const parsed = parseLayout(state, isFunction);
  if (!parsed) return fail(`LAYOUT ${name} IS DAMAGED: NOT LOADED`);
  applyLayout({ ...parsed, name });
  info(`LAYOUT ${name} LOADED`);
  afterPaint(() => series.layoutLoad.push(performance.now() - t0)); // submit to the new panels painted
  return true;
}

export async function deleteLayout(raw: string): Promise<boolean> {
  const name = normName(raw);
  if (!name) return fail("LAYOUT NAME: 1-32 OF A-Z 0-9 _ . -");
  try {
    await workspaceApi.deleteLayout(name);
  } catch (e) {
    return fail((e as ApiError).status === 404 ? `NO LAYOUT ${name}` : `LAYOUT ${name} NOT DELETED: ${errMessage(e)}`);
  }
  if (workspace.get().name === name) setLayoutName(undefined);
  info(`LAYOUT ${name} DELETED`);
  // Ignored on purpose: this only refreshes the layout NAMES used for autocomplete, after the save/delete above already
  // succeeded and said so. A real use of the list (typing LAYOUT ...) refetches and reports a failure then.
  void refreshLayouts().catch(() => {});
  return true;
}

/**
 * `LAYOUT SAVE|LOAD|DEL name` and `LAYOUT name` (= LOAD). Returns null for a bare `LAYOUT` (the
 * caller opens the list panel), else whether the command was accepted. The action itself is async
 * and reports through the status line.
 */
export function layoutCommand(args: string[]): boolean | null {
  if (!args.length) return null;
  const sub = args[0].toUpperCase();
  if (sub === "SAVE") {
    const name = args[1] ?? workspace.get().name;
    if (!name) return fail("LAYOUT SAVE NEEDS A NAME, E.G. LAYOUT SAVE DESK");
    void saveLayout(name);
  } else if (sub === "LOAD") {
    if (!args[1]) return fail("LAYOUT LOAD NEEDS A NAME (CTRL+O LISTS THEM)");
    void loadLayout(args[1]);
  } else if (sub === "DEL" || sub === "DELETE") {
    if (!args[1]) return fail("LAYOUT DEL NEEDS A NAME");
    void deleteLayout(args[1]);
  } else if (args.length === 1) {
    void loadLayout(args[0]);
  } else {
    return fail("USAGE: LAYOUT [SAVE|LOAD|DEL] NAME");
  }
  return true;
}
