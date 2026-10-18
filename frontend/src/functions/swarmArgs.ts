/** `SWARM`, `SWARM LIST`, `SWARM <PRESET> [subject...]`, `SWARM REPLAY <id>` (pure, unit-tested). */
export const PRESET_CODES = ["COMMITTEE", "RISK", "EARNINGS", "MACRO", "QUANT"] as const;
export type SwarmArgs =
  | { mode: "list" }
  | { mode: "run"; preset: string; subject: string }
  | { mode: "replay"; runId: string }
  | { mode: "bad"; error: string };

export const RUN_ID = /^[0-9a-f]{12}$/;

export function swarmArgs(args: string[]): SwarmArgs {
  const first = (args[0] ?? "").toUpperCase();
  if (!first || first === "LIST") return { mode: "list" };
  if (first === "REPLAY") {
    const id = (args[1] ?? "").toLowerCase();
    return RUN_ID.test(id) && args.length === 2 ? { mode: "replay", runId: id } : { mode: "bad", error: "USAGE: SWARM REPLAY <run id> (SWARM lists stored runs)" };
  }
  if ((PRESET_CODES as readonly string[]).includes(first)) {
    const subject = args.slice(1).join(" ").trim();
    if (!subject && first !== "MACRO") return { mode: "bad", error: `USAGE: SWARM ${first} <subject> (a ticker or a portfolio name)` };
    return { mode: "run", preset: first, subject };
  }
  return { mode: "bad", error: `UNKNOWN PRESET ${first.slice(0, 20)}: ${PRESET_CODES.join(" ")}` };
}

/** The ticker a SWARM subject starts with (upper case first word shaped like a symbol), or null. */
export function subjectSymbol(subject: string): string | null {
  const first = subject.trim().split(/\s+/)[0] ?? "";
  return /^[A-Z][A-Z0-9.\-^=]{0,11}$/.test(first) ? first : null;
}
