/**
 * OSA keys (pure, unit-tested): add `step` to a KEY=number argument, adding it when missing and never going below `min`.
 * `stepArg(["LEGS=..", "DAYS=7"], "DAYS", 7, 0)` -> ["LEGS=..", "DAYS=14"].
 */
export function stepArg(args: readonly string[], key: string, step: number, min: number): string[] {
  const re = new RegExp(`^${key}=(-?[\\d.]+)$`, "i");
  const i = args.findIndex((a) => re.test(a));
  const now = i < 0 ? 0 : Number(re.exec(args[i])![1]);
  const next = Math.max(min, now + step);
  const word = `${key}=${next}`;
  return i < 0 ? [...args, word] : args.map((a, j) => (j === i ? word : a));
}
