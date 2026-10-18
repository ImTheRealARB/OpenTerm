/** `AI [question...]`, `AI BT <idea>`, `AI AUTO <hypothesis>`, `AI CHART [hint]` (pure, unit-tested). Only the first word picks a mode. */
export type AiArgs =
  | { mode: "ask" | "bt" | "chart" | "doc" | "docoff" | "auto"; text: string }
  | { mode: "docfiling"; text: string; symbol: string; form: string }
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
