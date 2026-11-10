/** `MCP`, `MCP ENABLE <server> [YES]`, `MCP DISABLE <server>`, `MCP TEST <server>`, `MCP ALLOW <server> <tool>`, `MCP DENY <server> <tool>` (pure, unit-tested).
 * Server and tool names keep their case (tool names are case-sensitive); only the first word is a keyword. ENABLE needs `YES` after the notice was shown. */
export type McpArgs =
  | { mode: "list" }
  | { mode: "enable"; name: string; confirmed: boolean }
  | { mode: "disable" | "test"; name: string }
  | { mode: "allow" | "deny"; name: string; tool: string }
  | { mode: "bad"; error: string };

const USAGE = "USAGE: MCP | MCP ENABLE <server> [YES] | MCP DISABLE <server> | MCP TEST <server> | MCP ALLOW <server> <tool> | MCP DENY <server> <tool>";

export function mcpArgs(args: string[]): McpArgs {
  if (!args.length) return { mode: "list" };
  const first = args[0].toUpperCase();
  const name = (args[1] ?? "").toLowerCase();
  if (first === "ENABLE" && name && (args.length === 2 || (args.length === 3 && args[2].toUpperCase() === "YES"))) return { mode: "enable", name, confirmed: args.length === 3 };
  if ((first === "DISABLE" || first === "TEST") && name && args.length === 2) return { mode: first === "TEST" ? "test" : "disable", name };
  if ((first === "ALLOW" || first === "DENY") && name && args[2] && args.length === 3) return { mode: first === "ALLOW" ? "allow" : "deny", name, tool: args[2] };
  return { mode: "bad", error: USAGE };
}

/** The allow-list after turning one tool on or off (sorted, no duplicates). */
export function withTool(allow: string[], tool: string, on: boolean): string[] {
  const s = new Set(allow);
  if (on) s.add(tool);
  else s.delete(tool);
  return [...s].sort();
}

/** What `E` does: the first press shows the notice, the second (or `YES`) enables. */
export function enableStep(pending: string | null, name: string, confirmed: boolean): "ask" | "enable" {
  return confirmed || pending === name ? "enable" : "ask";
}
