/**
 * AI panel logic (pure, unit-tested): the SSE parser for `POST /api/ai/chat`, the reducer that turns events into one chat turn, and the
 * citation splitter. Nothing here talks to the network or the DOM.
 */
export type AiEvent =
  | { type: "start"; model: string; provider: string; started: string; fixtures?: boolean }
  | { type: "token"; text: string }
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; ok: boolean; empty: boolean; source: string | null; age_s: number | null; stale: boolean; bytes: number; summary: string }
  | { type: "usage"; prompt_tokens: number; completion_tokens: number; cost: number | null }
  | { type: "notice"; text: string }
  | { type: "error"; kind: string; text: string }
  | { type: "done"; answer: string; grounded: boolean; label: string | null; unsourced: string[]; tool_calls: number; cost: number; stopped: string | null };

export interface ToolRow {
  id: string;
  name: string;
  args: Record<string, unknown>;
  state: "running" | "ok" | "empty" | "failed";
  source?: string | null;
  age_s?: number | null;
  stale?: boolean;
  summary?: string;
}

export interface Turn {
  question: string;
  answer: string;
  tools: ToolRow[];
  notices: string[];
  status: "running" | "done" | "error";
  model: string;
  provider: string;
  started: string;
  fixtures: boolean;
  cost: number;
  label: string | null;
  unsourced: string[];
  error?: { kind: string; text: string };
}

export function newTurn(question: string): Turn {
  return { question, answer: "", tools: [], notices: [], status: "running", model: "", provider: "", started: "", fixtures: false, cost: 0, label: null, unsourced: [] };
}

/** Whole `data:` events in `buf`; whatever is left over (a partial event) comes back in `rest`. */
export function parseSse(buf: string): { events: AiEvent[]; rest: string } {
  const parts = buf.replace(/\r\n/g, "\n").split("\n\n");
  const rest = parts.pop() ?? "";
  const events: AiEvent[] = [];
  for (const block of parts) {
    for (const line of block.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      try {
        events.push(JSON.parse(line.slice(6)) as AiEvent);
      } catch {
        /* a broken line is skipped, never shown as data */
      }
    }
  }
  return { events, rest };
}

export function reduceTurn(t: Turn, e: AiEvent): Turn {
  switch (e.type) {
    case "start":
      return { ...t, model: e.model, provider: e.provider, started: e.started, fixtures: !!e.fixtures };
    case "token":
      return { ...t, answer: t.answer + e.text };
    case "tool_call":
      return { ...t, tools: [...t.tools, { id: e.id, name: e.name, args: e.args, state: "running" }] };
    case "tool_result":
      return {
        ...t,
        tools: t.tools.map((r) =>
          r.id === e.id ? { ...r, state: !e.ok ? "failed" : e.empty ? "empty" : "ok", source: e.source, age_s: e.age_s, stale: e.stale, summary: e.summary } : r,
        ),
      };
    case "usage":
      return { ...t, cost: t.cost + (e.cost ?? 0) };
    case "notice":
      return { ...t, notices: [...t.notices, e.text] };
    case "error":
      return { ...t, status: "error", error: { kind: e.kind, text: e.text } };
    case "done":
      return { ...t, status: "done", answer: e.answer, label: e.label, unsourced: e.unsourced, cost: e.cost };
  }
}

/** "AI · model · 10:00:00Z · MODEL OUTPUT, NOT DATA · US$0.0010": the line every AI answer carries. */
export function turnLine(t: Turn): string {
  const time = t.started ? t.started.slice(11, 19) + "Z" : "";
  return ["AI", t.model, time, "MODEL OUTPUT, NOT DATA", `US$${t.cost.toFixed(4)}`].filter(Boolean).join(" · ");
}

export type Segment = { text: string } | { cite: string };

export function citeSegments(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(/\[(T\d+)\]/g)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index) });
    out.push({ cite: m[1] });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}
