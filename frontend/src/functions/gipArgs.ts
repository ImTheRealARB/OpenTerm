/** GIP arguments (pure): `GIP [SYM] [1S|5S|15S|1M]`. The bar size is how ticks are bucketed into candles. */
export type GipBar = "1S" | "5S" | "15S" | "1M";
export const GIP_BARS: GipBar[] = ["1S", "5S", "15S", "1M"];
export const GIP_DEFAULT: GipBar = "5S";

export function parseGipArgs(args: string[]): { bar: GipBar } {
  for (const a of args) {
    const u = a.toUpperCase();
    if ((GIP_BARS as string[]).includes(u)) return { bar: u as GipBar };
    if (u === "1MIN" || u === "MIN") return { bar: "1M" };
  }
  return { bar: GIP_DEFAULT };
}

/** The `bar` query value of /api/world/ticks. */
export const gipApiBar = (b: GipBar): string => b.toLowerCase();

export const nextGipBar = (b: GipBar): GipBar => GIP_BARS[(GIP_BARS.indexOf(b) + 1) % GIP_BARS.length];

export const GIP_SECONDS: Record<GipBar, number> = { "1S": 1, "5S": 5, "15S": 15, "1M": 60 };
