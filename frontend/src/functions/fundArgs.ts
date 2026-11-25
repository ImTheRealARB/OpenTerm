/**
 * Phase 29 argument parsing (pure, vitest-able): turns the words typed after GF / FRM / IBQ / EQS BT into the query the
 * backend's `/api/fund/<fn>` route reads. `KEY=VALUE` words become parameters; bare words are matched by shape.
 */

type Params = Record<string, string>;

/** Same list as backend fund/metrics.py METRICS (test_ts_mirrors-style guard: fundArgs.test.ts checks the backend file). */
export const GF_METRICS = ["DE", "EPS", "EVEBITDA", "FCF", "GM", "NI", "NM", "OM", "PB", "PE", "PS", "REVENUE", "ROE", "ROIC"] as const;

/** `KEY=VALUE` words as an upper-case-keyed map, plus the remaining bare words. */
function split(args: string[]): { kv: Params; bare: string[] } {
  const kv: Params = {};
  const bare: string[] = [];
  for (const a of args) {
    const i = a.indexOf("=");
    if (i > 0) kv[a.slice(0, i).toUpperCase()] = a.slice(i + 1);
    else if (a.trim()) bare.push(a);
  }
  return { kv, bare };
}

/** GF: `[METRIC] [Q] [VS=MSFT,GOOGL]`. An unknown metric is passed on so the server names the valid list. */
export function gfParams(args: string[]): Params {
  const { kv, bare } = split(args);
  const out: Params = {};
  for (const w of bare.map((b) => b.toUpperCase())) {
    if (w === "Q" || w === "A") out.period = w;
    else if (!out.metric) out.metric = w;
  }
  if (kv.VS) out.vs = kv.VS.toUpperCase();
  return out;
}

/** FRM: `<TAG> [CY2024|CY2024Q4|CY2024Q4I] [UNIT=USD] [ASOF=YYYY-MM-DD]`. null = no tag (show the usage line). Tags keep their case. */
export function frmParams(args: string[]): Params | null {
  const { kv, bare } = split(args);
  const tag = bare.find((b) => !/^CY\d{4}/i.test(b));
  if (!tag) return null;
  const out: Params = { tag };
  const period = bare.find((b) => /^CY\d{4}(Q[1-4]I?)?$/i.test(b));
  if (period) out.period = period.toUpperCase();
  if (kv.ASOF) out.asof = kv.ASOF;
  if (kv.UNIT) out.unit = kv.UNIT;
  return out;
}

/** IBQ: `[YEAR] [INDUSTRY|SECTOR]`. */
export function ibqParams(args: string[]): Params {
  const out: Params = {};
  for (const w of args.map((a) => a.toUpperCase())) {
    if (/^\d{4}$/.test(w)) out.year = w;
    else if (w.startsWith("IND")) out.by = "industry";
    else if (w.startsWith("SEC")) out.by = "sector";
    else if (w === "SIC" || w === "BY=SIC") out.by = "sic";
    else if (w.startsWith("DIV") || w === "BY=DIV") out.by = "division";
  }
  return out;
}

/** EQS BT: `BT <RULES...> UNIV=LIST:A,B [FROM=2021] [VS=SPY]` (the leading BT is already removed). null = no rules. */
export function eqsBtParams(args: string[]): Params | null {
  const { kv, bare } = split(args);
  if (!bare.length) return null;
  const out: Params = { rules: bare.join(" ").toUpperCase() };
  // Rule words contain < or >, never =, unless typed as >= / <=: put those back into the rules.
  for (const [k, v] of Object.entries(kv)) {
    if (k.endsWith(">") || k.endsWith("<")) out.rules += ` ${k}=${v.toUpperCase()}`;
  }
  if (kv.UNIV) out.univ = kv.UNIV.toUpperCase();
  if (kv.FROM) out.start = kv.FROM;
  if (kv.VS) out.vs = kv.VS.toUpperCase();
  return out;
}

/** True when EQS was typed as the screen backtest (`EQS BT ...`). */
export function isEqsBt(args: string[]): boolean {
  return (args[0] ?? "").toUpperCase() === "BT";
}
