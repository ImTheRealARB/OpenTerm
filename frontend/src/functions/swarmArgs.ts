/**
 * `SWARM`, `SWARM LIST`, `SWARM <DESK> [subject...] [NAME=value ...] [--force]`, `SWARM REPLAY <id>` (pure, unit-tested).
 *
 * The desks are NOT hardcoded here: the backend lists every desk (built-in, packaged and the user's own YAML files) at
 * `GET /api/ai/swarm/presets`, and the panel passes that list in. The list is only used to understand `NAME=value` pairs
 * and to give a usage message early; the server stays the judge of whether a desk exists (it answers 400 with the valid codes).
 */
export type Coverage = "FULL" | "PARTIAL" | "UNAVAILABLE";

export interface VariableInfo {
  name: string;
  description: string;
  required: boolean;
}

/** One desk as `GET /api/ai/swarm/presets` returns it (shape: backend `swarm.listing` + the USD figure added by the route). */
export interface PresetInfo {
  code: string;
  title: string;
  roles: { id: string; title: string; tools: string[] }[];
  note: string;
  needs_subject: boolean;
  coverage: Coverage;
  limits: string[]; // what a PARTIAL / UNAVAILABLE desk cannot do
  kind: "lite" | "dag";
  variables: VariableInfo[];
  source: string; // "built-in", a packaged file or "user:<file>"
  estimate: { roles: number; in_tokens: number; out_tokens: number; usd: number | null };
}

/** The whole answer of `GET /api/ai/swarm/presets`. */
export interface PresetsResponse {
  presets: PresetInfo[];
  errors: Record<string, string>; // preset files that failed to load: file name -> why
  model: string;
  spend: { today: number; cap: number };
}

export type SwarmArgs =
  | { mode: "list" }
  | { mode: "run"; preset: string; subject: string; variables: Record<string, string>; force: boolean }
  | { mode: "replay"; runId: string }
  | { mode: "bad"; error: string };

export const RUN_ID = /^[0-9a-f]{12}$/;
/** A desk code as the backend accepts it (`swarm.CODE_RE`): 2-14 characters, A-Z 0-9 _. */
export const CODE_SHAPE = /^[A-Z][A-Z0-9_]{1,13}$/;
const PAIR = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/;

export function swarmArgs(args: string[], presets: PresetInfo[] = []): SwarmArgs {
  const first = (args[0] ?? "").toUpperCase();
  if (!first || first === "LIST") return { mode: "list" };
  if (first === "REPLAY") {
    const id = (args[1] ?? "").toLowerCase();
    return RUN_ID.test(id) && args.length === 2 ? { mode: "replay", runId: id } : { mode: "bad", error: "USAGE: SWARM REPLAY <run id> (SWARM lists stored runs)" };
  }
  if (!CODE_SHAPE.test(first)) return { mode: "bad", error: `UNKNOWN DESK ${first.slice(0, 20)}: SWARM LISTS THE DESKS` };

  const desk = presets.find((p) => p.code === first);
  const declared = new Map((desk?.variables ?? []).map((v) => [v.name.toLowerCase(), v.name]));
  const variables: Record<string, string> = {};
  const words: string[] = [];
  let force = false;
  for (const tok of args.slice(1)) {
    if (tok.toLowerCase() === "--force") {
      force = true;
      continue;
    }
    const m = PAIR.exec(tok);
    const name = m ? declared.get(m[1].toLowerCase()) : undefined;
    // Only a declared variable name counts as a pair: "GC=F" and "EURUSD=X" are tickers and stay part of the subject.
    if (m && name) {
      if (!m[2]) return { mode: "bad", error: `USAGE: ${name.toUpperCase()}=<value> NEEDS A VALUE` };
      variables[name] = m[2];
    } else words.push(tok);
  }
  const subject = words.join(" ").trim();

  if (desk?.coverage === "UNAVAILABLE") return { mode: "bad", error: `${first} IS UNAVAILABLE: ${desk.limits.join("; ") || "SEE SWARM"}` };
  if (desk && desk.variables.length > 0) {
    // Same rule as the server (`swarm.resolve_variables`): the subject text fills the first variable still empty.
    const filled = new Set(Object.keys(variables));
    const firstOpen = subject ? desk.variables.find((v) => !filled.has(v.name)) : undefined;
    if (firstOpen) filled.add(firstOpen.name);
    const missing = desk.variables.filter((v) => v.required && !filled.has(v.name));
    if (missing.length > 0) {
      const pairs = desk.variables.map((v) => `${v.name.toUpperCase()}=<${v.required ? "value" : "optional"}>`).join(" ");
      return { mode: "bad", error: `USAGE: SWARM ${first} ${pairs} (OR JUST THE ${desk.variables[0].name.toUpperCase()} AFTER THE DESK NAME)` };
    }
  } else {
    // A desk we do not know yet (or one without variables) needs a subject unless the list says it does not.
    const needsSubject = desk ? desk.needs_subject : true;
    if (needsSubject && !subject) return { mode: "bad", error: `USAGE: SWARM ${first} <subject> (a ticker or a portfolio name)` };
  }
  return { mode: "run", preset: first, subject, variables, force };
}

/** The command that repeats a run (used to tell the user how to force it past the spend cap). */
export function commandFor(a: { preset: string; subject: string; variables: Record<string, string> }, extra = ""): string {
  const pairs = Object.entries(a.variables).map(([k, v]) => `${k.toUpperCase()}=${v}`);
  return ["SWARM", a.preset, a.subject, ...pairs, extra].filter(Boolean).join(" ");
}

/** The ticker a SWARM subject starts with (upper case first word shaped like a symbol), or null. */
export function subjectSymbol(subject: string): string | null {
  const first = subject.trim().split(/\s+/)[0] ?? "";
  return /^[A-Z][A-Z0-9.\-^=]{0,11}$/.test(first) ? first : null;
}

/** Plain-English label for a desk's coverage: FULL needs no reason; PARTIAL and UNAVAILABLE always say what is missing. */
export function coverageLabel(p: { coverage: Coverage; limits: string[] }): string {
  return p.coverage === "FULL" ? "FULL" : `${p.coverage}: ${p.limits.join("; ")}`;
}
