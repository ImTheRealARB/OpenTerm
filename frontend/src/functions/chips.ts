/**
 * Question chips (Phase 32): 2 or 3 suggested questions per table panel. `?` shows them, 1-3 opens AI with that question.
 * Pure (no React, no network) so vitest can check it.
 *
 * Each question names the tool that reads the same data the panel shows (the `board` tool for the macro boards, `qry` for QRY,
 * `research` / `news` for company tables), so the answer is grounded in that data and cites the tool call; an answer that used no
 * tool data is still marked UNGROUNDED by the AI panel. The questions are plain prompts: nothing is sent until you pick one.
 */

const BOARD: Record<string, string[]> = {
  mmr: ["Using the board tool with fn mmr: how far apart are SOFR, EFFR, ESTR and SONIA today, and which moved most over the last month?",
    "Using the board tool with fn mmr: is SOFR trading near the top or the bottom of its daily percentile range?"],
  nowc: ["Using the board tool with fn nowc: how has the GDPNow nowcast for this quarter changed, and which data releases moved it most?",
    "Using the board tool with fn nowc: how close were recent final nowcasts to the BEA advance estimates?"],
  ecfc: ["Using the board tool with fn ecfc: compare the IMF, OECD and SPF forecasts for US growth and inflation this year and next.",
    "Using the board tool with fn ecfc: where do the FOMC projections differ most from private forecasters?"],
  fomc: ["Using the board tool with fn fomc: what changed in the latest FOMC statement versus the previous one, word for word?",
    "Using the board tool with fn fomc: how wide is the spread of the fed funds dots for each year?"],
  wb: ["Using the board tool with fn wb: which 10-year government yields are highest, and which moved most recently?",
    "Using the board tool with fn wb: how do European and Japanese yields compare with US 10-year?"],
  crpr: ["Using the board tool with fn crpr: are credit spreads tight or wide versus the range FRED shows?",
    "Using the board tool with fn crpr: how have high-yield spreads moved against investment grade over the last month?"],
  fwcv: ["Using the board tool with fn fwcv: what do the forward rates imply for the 1-year rate in 1, 2 and 5 years?",
    "Using the board tool with fn fwcv: where is the curve steepest, and what does 5y5y say?"],
  btmm: ["Using the board tool with fn btmm and country {C}: what stands out in this country monitor?",
    "Using the board tool with fn btmm and country {C}: which items are stale or missing, and why does that matter?"],
  wcrs: ["Using the board tool with fn wcrs: which currencies gained most against USD and against INR this month?",
    "Using the board tool with fn wcrs: which currencies reversed between the 1-month and year-to-date ranks?"],
  cdr: ["Using the board tool with fn cdr: which exchanges are closed or close early in the next 30 days?"],
  ctm: ["Using the board tool with fn ctm and root {R}: when do the front contracts stop trading, and when is first notice?"],
  tsys: ["Using the board tool with fn tsys: how did the recent Treasury auctions go by bid-to-cover and high yield?",
    "Using the board tool with fn tsys: what is coming up in the announced auctions?"],
  nrgf: ["Using the board tool with fn nrgf: how do US crude and product inventories compare with their 2-year range?"],
  agri: ["Using the board tool with fn agri: what changed between the last two WASDE projections for US corn and soybeans?"],
  re: ["Using the board tool with fn re: what do house prices, starts and mortgage rates say about US housing now?"],
  wpe: ["Using the board tool with fn wpe: which markets look cheapest and most expensive by P/E and P/B (these are ETF proxies)?",
    "Using the board tool with fn wpe: how does the US P/E compare with Europe, Japan and emerging markets?"],
};

/** The questions for one panel. `fn` is the ResearchPanel route name (lowercase), `symbol` the panel's security, `args` its arguments,
 * `row` the selected row (RES asks about that paper). */
export function chipsFor(fn: string, symbol: string | null, title: string, args: string[], row?: { title?: unknown; url?: unknown }): string[] {
  const f = fn.toLowerCase();
  if (f === "res" && typeof row?.url === "string" && typeof row.title === "string") {
    // RES summaries are on demand: AI reads the paper page with read_url only after the user picks one of these.
    return [`Use read_url on ${row.url} and summarise the paper "${row.title}": its question, data and method, and main findings, in at most 6 bullets that quote the page.`,
      `Use read_url on ${row.url}: what does "${row.title}" imply for markets or policy, according to the paper itself?`];
  }
  if (BOARD[f]) {
    const c = (args[0] ?? "US").toUpperCase();
    const r = (args[0] ?? "CL").toUpperCase();
    return BOARD[f].map((q) => q.replace("{C}", c).replace("{R}", r));
  }
  if (f === "qry" && args.length) {
    const q = `QRY ${args.join(" ")}`;
    return [`Using the qry tool, run "${q}" and summarise what the result shows.`,
      `Using the qry tool, run "${q}"; which rows stand out and why might that be?`];
  }
  if (f === "cn" && symbol) {
    return [`Digest the latest headlines for ${symbol}: call the news tool for ${symbol}, then write at most 8 bullets, each citing the tool call and giving the headline's time and source; add nothing that is not in the headlines.`,
      `Using the news tool for ${symbol}: which headlines could move the stock, and which are repeats of the same story?`];
  }
  const sym = symbol ? ` for ${symbol}` : "";
  const name = title || fn.toUpperCase();
  return [`Using the research tool where it helps: summarise what the ${name} table shows${sym} and what stands out.`,
    `What should I check next after looking at ${name}${sym}, and which OpenTerm function would show it?`];
}

/** The flash line that lists the chips. */
export function chipLine(chips: string[]): string {
  return `ASK AI (PRESS 1-${chips.length}, ESC CANCELS): ` + chips.map((c, i) => `${i + 1} ${c}`).join("  ·  ");
}
