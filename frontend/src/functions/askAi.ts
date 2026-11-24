/**
 * Phase 32: open AI next to the current panel with a question (question chips). The panel that asked stays visible, so the
 * user reads the answer beside the data it is about. The question goes in as the AI panel's args, exactly like typing
 * `AI <question>`, so it passes through the same aiArgs parsing, spend checks and grounding labels.
 */
import { navigate, splitOrSay } from "../state/workspace";

export function askAi(question: string, say: (text: string) => void): void {
  const id = splitOrSay("v", say); // says PANEL LIMIT when there is no room; nothing is sent then
  if (id === null) return;
  navigate(id, { fn: "AI", args: question.split(/\s+/).filter(Boolean) });
}
