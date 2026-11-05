/** SWARM panel logic (pure, unit-tested): events of `POST /api/ai/swarm` (and a stored run's replay) reduced to one run state. Each role is a Turn. */
import { newTurn, reduceTurn, type AiEvent, type Turn } from "./aiStream";
import type { Coverage } from "./swarmArgs";

export interface RoleInfo {
  id: string;
  title: string;
  tools: string[];
}
/** Worst-case cost of a run, sent right after `swarm_start` (`usd` is null when the model's price is unknown). */
export interface Estimate {
  roles: number;
  in_tokens: number;
  out_tokens: number;
  usd: number | null;
  cap_left: number;
}

export type SwarmEvent =
  | {
      type: "swarm_start";
      preset: string;
      title: string;
      subject: string;
      model: string;
      provider: string;
      started: string;
      roles: RoleInfo[];
      fixtures?: boolean;
      coverage?: Coverage;
      limits?: string[];
      variables?: Record<string, string>;
    }
  | ({ type: "estimate" } & Estimate)
  | { type: "role_start"; role: string; title: string; tools: string[]; attempt: number }
  | { type: "role_retry"; role: string; attempt: number; why: string }
  | { type: "role_error"; role: string; kind: string; text: string }
  | { type: "role_done"; role: string; answer: string; grounded: boolean; label: string | null; unsourced: string[]; tool_calls: number; cost: number; stopped: string | null }
  | { type: "saved"; run_id: string }
  | { type: "replay"; run_id: string; kind: string; title: string; created_at: number }
  | { type: "swarm_done"; answer: string; cost: number; unsourced: string[]; grounded: boolean; label: string | null; failed: string[]; capped?: boolean }
  | { type: "error"; kind: string; text: string }
  | ({ role: string } & Extract<AiEvent, { type: "token" | "tool_call" | "tool_result" | "usage" | "notice" }>);

export interface RoleState {
  id: string;
  title: string;
  tools: string[];
  state: "waiting" | "running" | "done" | "failed";
  attempt: number;
  turn: Turn;
  errors: string[];
}

export interface SwarmState {
  preset: string;
  title: string;
  subject: string;
  model: string;
  started: string;
  fixtures: boolean;
  coverage: Coverage;
  limits: string[];
  variables: Record<string, string>;
  estimate?: Estimate;
  capped: boolean; // the run hit its output-token cap and stopped
  roles: RoleState[];
  status: "running" | "done" | "error";
  final?: { answer: string; unsourced: string[]; grounded: boolean; label: string | null; failed: string[] };
  cost: number;
  runId?: string;
  replayOf?: { runId: string; createdAt: number };
  error?: { kind: string; text: string };
}

export function newSwarm(): SwarmState {
  return { preset: "", title: "", subject: "", model: "", started: "", fixtures: false, coverage: "FULL", limits: [], variables: {}, capped: false, roles: [], status: "running", cost: 0 };
}

const mapRole = (s: SwarmState, id: string, f: (r: RoleState) => RoleState): SwarmState => ({ ...s, roles: s.roles.map((r) => (r.id === id ? f(r) : r)) });

export function reduceSwarm(s: SwarmState, e: SwarmEvent): SwarmState {
  switch (e.type) {
    case "swarm_start":
      return {
        ...s,
        preset: e.preset,
        title: e.title,
        subject: e.subject,
        model: e.model,
        started: e.started,
        fixtures: !!e.fixtures,
        coverage: e.coverage ?? "FULL",
        limits: e.limits ?? [],
        variables: e.variables ?? {},
        roles: e.roles.map((r) => ({ ...r, state: "waiting", attempt: 0, turn: newTurn(r.title), errors: [] })),
      };
    case "role_start":
      return mapRole(s, e.role, (r) => ({ ...r, state: "running", attempt: e.attempt, turn: { ...newTurn(r.title), model: s.model, started: s.started } }));
    case "role_retry":
      return mapRole(s, e.role, (r) => ({ ...r, errors: [...r.errors, `RETRY ${e.attempt}: ${e.why}`] }));
    case "role_error":
      return mapRole(s, e.role, (r) => ({ ...r, state: "failed", errors: [...r.errors, e.text] }));
    case "role_done": {
      const done: AiEvent = { type: "done", answer: e.answer, grounded: e.grounded, label: e.label, unsourced: e.unsourced, tool_calls: e.tool_calls, cost: e.cost, stopped: e.stopped };
      return { ...mapRole(s, e.role, (r) => ({ ...r, state: "done", turn: reduceTurn(r.turn, done) })), cost: s.cost + e.cost };
    }
    case "estimate":
      return { ...s, estimate: { roles: e.roles, in_tokens: e.in_tokens, out_tokens: e.out_tokens, usd: e.usd, cap_left: e.cap_left } };
    case "saved":
      return { ...s, runId: e.run_id };
    case "replay":
      return { ...s, replayOf: { runId: e.run_id, createdAt: e.created_at } };
    case "swarm_done":
      return { ...s, status: "done", cost: e.cost, capped: !!e.capped, final: { answer: e.answer, unsourced: e.unsourced, grounded: e.grounded, label: e.label, failed: e.failed } };
    case "error":
      return { ...s, status: "error", error: { kind: e.kind, text: e.text } };
    default:
      // token, tool_call, tool_result, usage, notice: all carry their role
      return mapRole(s, e.role, (r) => ({ ...r, turn: reduceTurn(r.turn, e) }));
  }
}

/** "1.2M" / "340K" for token counts. */
const kilo = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : `${Math.max(1, Math.round(n / 1e3))}K`);

/** The cost line shown before and during a run. It is a worst case (every round used, every tool result full size): real runs cost far less. */
export function estimateLine(e: { in_tokens: number; out_tokens: number; usd: number | null; cap_left?: number }): string {
  const money = e.usd === null ? "PRICE UNKNOWN FOR THIS MODEL" : `US$${e.usd.toFixed(2)}`;
  const cap = e.cap_left === undefined ? "" : ` · US$${Math.max(0, e.cap_left).toFixed(2)} LEFT OF TODAY'S CAP`;
  return `WORST CASE ${kilo(e.in_tokens)} TOKENS READ + ${kilo(e.out_tokens)} WRITTEN · ${money}${cap}`;
}
