/** `AI [question...]`, `AI BT <idea>`, `AI AUTO <hypothesis>`, `AI CHART [hint]`, `AI FILING <SYMBOL> [10-K|10-Q] <question | DRIVERS | GUIDANCE | CHAIN>` (pure, unit-tested).
 * Only the first word picks a mode. */
export type AiArgs =
  | { mode: "ask" | "bt" | "chart" | "doc" | "docoff" | "auto"; text: string }
  | { mode: "docfiling"; text: string; symbol: string; form: string }
  | { mode: "filing"; text: string; symbol: string; form: string | null; drivers: boolean; preset?: "guidance" | "chain" }
  | { mode: "bad"; text: string; error: string };

export function aiArgs(args: string[]): AiArgs {
  const first = (args[0] ?? "").toUpperCase();
  if (first === "BT") {
    const text = args.slice(1).join(" ").trim();
    return text ? { mode: "bt", text } : { mode: "bad", text: "", error: "USAGE: AI BT <strategy idea in words>" };
  }
  if (first === "AUTO") {
    const text = args.slice(1).join(" ").trim();
    return text ? { mode: "auto", text } : { mode: "bad", text: "", error: "USAGE: AI AUTO <hypothesis in words>" };
  }
  if (first === "FILING") return filingArgs(args.slice(1));
  if (first === "DOC") {
    const sub = (args[1] ?? "").toUpperCase();
    if (!sub) return { mode: "doc", text: "" };
    if (sub === "OFF" && args.length === 2) return { mode: "docoff", text: "" };
    if (sub === "FILING" && args[2] && args.length <= 4) return { mode: "docfiling", text: "", symbol: args[2].toUpperCase(), form: (args[3] ?? "10-K").toUpperCase() };
    return { mode: "bad", text: "", error: "USAGE: AI DOC [FILING <SYMBOL> [FORM]] | AI DOC OFF (U uploads a file)" };
  }
  if (first === "CHART") return { mode: "chart", text: args.slice(1).join(" ").trim() };
  return { mode: "ask", text: args.join(" ").trim() };
}

const FILING_USAGE = "USAGE: AI FILING <SYMBOL> [10-K|10-Q] <question> | AI FILING <SYMBOL> DRIVERS|GUIDANCE|CHAIN (US FILERS ONLY)";

/** `AAPL [10-K|10-Q] DRIVERS|GUIDANCE|CHAIN` or `AAPL [10-K|10-Q] <question words>`. The form is optional: without it the newest 10-K or 10-Q is used. */
function filingArgs(rest: string[]): AiArgs {
  const symbol = (rest[0] ?? "").toUpperCase();
  if (!/^[A-Z0-9.^=-]{1,12}$/.test(symbol)) return { mode: "bad", text: "", error: FILING_USAGE };
  let words = rest.slice(1);
  const f = (words[0] ?? "").toUpperCase();
  const form = f === "10-K" || f === "10-Q" ? f : null;
  if (form) words = words.slice(1);
  if (words.length === 1 && words[0].toUpperCase() === "DRIVERS") return { mode: "filing", text: "DRIVERS", symbol, form, drivers: true };
  if (words.length === 1 && ["GUIDANCE", "CHAIN"].includes(words[0].toUpperCase())) {
    const w = words[0].toUpperCase();
    return { mode: "filing", text: w, symbol, form, drivers: false, preset: w === "GUIDANCE" ? "guidance" : "chain" };
  }
  const text = words.join(" ").trim();
  return text ? { mode: "filing", text, symbol, form, drivers: false } : { mode: "bad", text: "", error: FILING_USAGE };
}
