/** `JOBS TEST [steps] [ms]`: the demo job. Pure so vitest can test it. */
export type JobsArgs = { kind: "none" } | { kind: "test"; steps: number; step_ms: number } | { kind: "error"; message: string };

export const JOBS_USAGE = "USAGE: JOBS TEST [STEPS] [MS]";

const intIn = (s: string | undefined, def: number, lo: number, hi: number): number | null => {
  if (s === undefined) return def;
  if (!/^\d+$/.test(s)) return null;
  const n = Number(s);
  return n >= lo && n <= hi ? n : null;
};

export function parseJobsArgs(args: string[]): JobsArgs {
  if (!args.length) return { kind: "none" };
  if (args[0].toUpperCase() !== "TEST" || args.length > 3) return { kind: "error", message: JOBS_USAGE };
  const steps = intIn(args[1], 20, 1, 100_000);
  const step_ms = intIn(args[2], 100, 0, 60_000);
  if (steps === null || step_ms === null) return { kind: "error", message: `${JOBS_USAGE} (STEPS 1-100000, MS 0-60000)` };
  return { kind: "test", steps, step_ms };
}
