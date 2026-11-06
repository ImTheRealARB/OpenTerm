/**
 * AI panel logic (pure, unit-tested): the reducer that turns the events of `POST /api/ai/chat` (parsed by net/sse.ts) into one chat turn, and the
 * citation splitter. Nothing here talks to the network or the DOM.
 */
export type AiEvent =
  | { type: "start"; model: string; provider: string; started: string; fixtures?: boolean }
  | { type: "token"; text: string }
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; ok: boolean; empty: boolean; source: string | null; age_s: number | null; stale: boolean; bytes: number; summary: string }
  | { type: "usage"; prompt_tokens: number; completion_tokens: number; cost: number | null }
  | { type: "notice"; text: string }
  | { type: "draft"; draft: BtDraft }
  | { type: "draft_error"; text: string }
  | { type: "evidence"; runs: string[]; tested: boolean; note: string }
  | { type: "saved"; run_id: string }
  | { type: "filing"; symbol: string; form: string; filed: string; accession: string; url: string; source: string; sections: number; passages: number; mode: string }
  | { type: "passages"; items: FilingPassage[] }
  | { type: "quotes"; items: FilingQuote[] }
  | { type: "error"; kind: string; text: string }
  | { type: "done"; answer: string; grounded: boolean; label: string | null; unsourced: string[]; tool_calls: number; cost: number; stopped: string | null; verified?: number; unverified?: number };

/** `AI FILING`: the filing the answer came from (form, dates, accession, source). */
export interface FilingInfo {
  symbol: string;
  form: string;
  filed: string;
  accession: string;
  url: string;
  source: string;
  sections: number;
  passages: number;
  mode: string;
}
/** A passage sent to the model (P1, P2...), with the section it came from. */
export interface FilingPassage {
  id: string;
  section: string;
  chars: number;
  preview: string;
}
/** One quote the model gave, after the exact-match check. `verified` false = UNVERIFIED and its claim is not in the summary. */
export interface FilingQuote {
  n: number;
  claim: string;
  quote: string;
  claimed_section: string | null;
  section: string | null;
  verified: boolean;
  reason: string;
}

/** A backtest drafted by `AI BT`: validated by the BT parser, never run by the AI. */
export interface BtDraft {
  symbols: string[];
  rule: string;
  range: string;
  interval: string;
  rationale: string;
  command: string;
  note: string;
}

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
  draft?: BtDraft;
  draftError?: string;
  /** `AI AUTO`: the backtest runs behind the report (none = the report has no backtest evidence). */
  evidence?: { runs: string[]; tested: boolean; note: string };
  runId?: string;
  /** `AI FILING`: the filing, the passages sent to the model, and each quote with its verification. */
  filing?: FilingInfo;
  passages?: FilingPassage[];
  quotes?: FilingQuote[];
}

export function newTurn(question: string): Turn {
  return { question, answer: "", tools: [], notices: [], status: "running", model: "", provider: "", started: "", fixtures: false, cost: 0, label: null, unsourced: [] };
}

/** Cuts a still-running turn short (the panel was closed or moved to another view). A finished turn is returned unchanged. */
export function stopTurn(t: Turn, notice: string): Turn {
  return t.status === "running" ? { ...t, status: "done", label: "INCOMPLETE", notices: [...t.notices, notice] } : t;
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
    case "draft":
      return { ...t, draft: e.draft };
    case "draft_error":
      return { ...t, draftError: e.text };
    case "evidence":
      return { ...t, evidence: { runs: e.runs, tested: e.tested, note: e.note } };
    case "saved":
      return { ...t, runId: e.run_id };
    case "filing": {
      const { type: _type, ...info } = e;
      return { ...t, filing: info };
    }
    case "passages":
      return { ...t, passages: e.items };
    case "quotes":
      return { ...t, quotes: e.items };
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
  for (const m of text.matchAll(/\[([TQ]\d+)\]/g)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index) });
    out.push({ cite: m[1] });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}
