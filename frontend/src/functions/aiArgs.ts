/** `AI [question...]`, `AI BT <idea>`, `AI CHART [hint]` (pure, unit-tested). Only the first word picks a mode. */
export type AiArgs = { mode: "ask" | "bt" | "chart"; text: string } | { mode: "bad"; text: string; error: string };

export function aiArgs(args: string[]): AiArgs {
  const first = (args[0] ?? "").toUpperCase();
  if (first === "BT") {
    const text = args.slice(1).join(" ").trim();
    return text ? { mode: "bt", text } : { mode: "bad", text: "", error: "USAGE: AI BT <strategy idea in words>" };
  }
  if (first === "CHART") return { mode: "chart", text: args.slice(1).join(" ").trim() };
  return { mode: "ask", text: args.join(" ").trim() };
}
