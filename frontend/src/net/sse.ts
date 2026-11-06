/**
 * Server-sent events parser (pure, so vitest can run it in Node). The AI chat and SWARM answers stream as `data: {json}` blocks
 * separated by a blank line; `streamPost` (aiApi.ts) feeds this with each chunk it reads.
 */

/** Whole `data:` events in `buf`; whatever is left over (a partial event) comes back in `rest`. */
export function parseSse<E>(buf: string): { events: E[]; rest: string } {
  const parts = buf.replace(/\r\n/g, "\n").split("\n\n");
  const rest = parts.pop() ?? "";
  const events: E[] = [];
  for (const block of parts) {
    for (const line of block.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      try {
        events.push(JSON.parse(line.slice(6)) as E);
      } catch {
        /* a broken line is skipped, never shown as data */
      }
    }
  }
  return { events, rest };
}
