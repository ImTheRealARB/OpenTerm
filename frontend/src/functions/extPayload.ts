/**
 * EXT: the pure part. Reads the command, and turns an extension's payload into what the shared Grid and chart draw.
 * No React and no network here (vitest loads it anywhere). The backend (extensions/payload.py) has already checked the payload;
 * this still treats it as untrusted text: a cell is printed as text, never as markup.
 *
 *   EXT                      -> LIST
 *   EXT LIST
 *   EXT ENABLE <name> | EXT DISABLE <name>
 *   EXT <name> [route] [args...]   route is the first word when the extension has a route of that name, else `main`
 */
import type { BarData } from "../chart/ChartView";
import type { TableSection } from "../research/tablePayload";

export interface ExtColumn {
  key: string;
  title: string;
  kind: TableSection["columns"][number]["kind"];
  align: "left" | "right";
}

export interface ExtTable {
  kind: "table";
  title: string;
  columns: ExtColumn[];
  rows: Record<string, string | number | boolean | null>[];
  notes?: string[];
}

export interface ExtSeries {
  kind: "series";
  title: string;
  unit?: string;
  t: number[];
  v: (number | null)[];
}

export type ExtPayload = ExtTable | ExtSeries;

export interface ExtInfo {
  name: string;
  version: string | null;
  author: string | null;
  license: string | null;
  description: string;
  source: string;
  adds: string[];
  enabled: boolean;
  status: "ON" | "OFF" | "ERR";
  error: string | null;
  routes: { name: string; title: string; args: string }[];
  tools: string[];
}

export type ExtCommand =
  | { mode: "list" }
  | { mode: "enable" | "disable"; name: string }
  | { mode: "view"; name: string; route: string | null; rest: string[] }
  | { mode: "usage"; text: string };

export const EXT_USAGE = "USAGE: EXT [LIST] | EXT ENABLE <name> | EXT DISABLE <name> | EXT <name> [route] [args]";
const NAME = /^[a-z][a-z0-9_-]{0,31}$/;

/** The command's meaning. Names are lowercase on the wire; the command line upper-cases them, so they are lowered here. */
export function parseExtArgs(args: string[]): ExtCommand {
  const [first, second, ...more] = args;
  if (!first || first.toUpperCase() === "LIST") return { mode: "list" };
  const word = first.toUpperCase();
  if (word === "ENABLE" || word === "DISABLE") {
    const name = (second ?? "").toLowerCase();
    if (!NAME.test(name) || more.length > 0) return { mode: "usage", text: `USAGE: EXT ${word} <name> (NAMES COME FROM EXT LIST)` };
    return { mode: word === "ENABLE" ? "enable" : "disable", name };
  }
  const name = first.toLowerCase();
  if (!NAME.test(name)) return { mode: "usage", text: EXT_USAGE };
  return { mode: "view", name, route: null, rest: [second, ...more].filter((a): a is string => !!a) };
}

/** Splits `rest` into the route and its arguments, given the routes the (enabled) extension offers. */
export function pickRoute(rest: string[], routes: readonly string[]): { route: string; args: string[] } {
  const head = rest[0]?.toLowerCase();
  if (head && routes.includes(head)) return { route: head, args: rest.slice(1) };
  return { route: "main", args: rest };
}

/** One word for the status column and a colour class. */
export function statusClass(s: ExtInfo["status"]): "up" | "err" | "dim" {
  return s === "ON" ? "up" : s === "ERR" ? "err" : "dim";
}

/** A table payload as the one section the research tables use, so `gridColumns` and the Grid draw it unchanged. */
export function tableSection(p: ExtTable): TableSection {
  return {
    id: "ext",
    title: p.title,
    columns: p.columns.map((c) => ({ key: c.key, title: c.title.toUpperCase(), kind: c.kind, align: c.align })),
    rows: p.rows,
    note: null,
  };
}

/** A series payload as chart bars (open = high = low = close). A null value is skipped, not interpolated; the count is returned. */
export function seriesBars(p: ExtSeries): { bars: BarData; skipped: number } {
  const keep: number[] = [];
  for (let i = 0; i < p.v.length; i++) if (p.v[i] != null && Number.isFinite(p.v[i])) keep.push(i);
  const c = Float64Array.from(keep, (i) => p.v[i] as number);
  const interval = medianGapSeconds(p.t) >= 5 * 86400 ? "1mo" : "1d";
  return {
    bars: { symbol: p.unit || "EXT", interval, tz: "UTC", t: Float64Array.from(keep, (i) => p.t[i]), o: c, h: c, l: c, c, v: new Float64Array(keep.length) },
    skipped: p.v.length - keep.length,
  };
}

function medianGapSeconds(t: number[]): number {
  if (t.length < 2) return 0;
  const gaps = t.slice(1).map((x, i) => x - t[i]).sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)];
}

/** The "who is this from" line shown when an extension's data is on screen. */
export function provenance(x: Pick<ExtInfo, "name" | "version" | "author" | "license" | "source">): string {
  return `EXTENSION ${x.name.toUpperCase()} ${x.version ?? ""} BY ${(x.author ?? "UNKNOWN").toUpperCase()} (${(x.license ?? "?").toUpperCase()}, ${x.source.toUpperCase()}) · THIRD-PARTY CODE`;
}
