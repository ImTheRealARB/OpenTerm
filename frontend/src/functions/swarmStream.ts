/** SWARM panel logic (pure, unit-tested): events of `POST /api/ai/swarm` (and a stored run's replay) reduced to one run state. Each role is a Turn. */
import { newTurn, reduceTurn, type AiEvent, type Turn } from "./aiStream";

export interface RoleInfo {
  id: string;
  title: string;
  tools: string[];
}
export type SwarmEvent =
  | { type: "swarm_start"; preset: string; title: string; subject: string; model: string; provider: string; started: string; roles: RoleInfo[]; fixtures?: boolean }
  | { type: "role_start"; role: string; title: string; tools: string[]; attempt: number }
  | { type: "role_retry"; role: string; attempt: number; why: string }
  | { type: "role_error"; role: string; kind: string; text: string }
  | { type: "role_done"; role: string; answer: string; grounded: boolean; label: string | null; unsourced: string[]; tool_calls: number; cost: number; stopped: string | null }
  | { type: "saved"; run_id: string }
  | { type: "replay"; run_id: string; kind: string; title: string; created_at: number }
  | { type: "swarm_done"; answer: string; cost: number; unsourced: string[]; grounded: boolean; label: string | null; failed: string[] }
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
  roles: RoleState[];
  status: "running" | "done" | "error";
  final?: { answer: string; unsourced: string[]; grounded: boolean; label: string | null; failed: string[] };
  cost: number;
  runId?: string;
  replayOf?: { runId: string; createdAt: number };
  error?: { kind: string; text: string };
}

export function newSwarm(): SwarmState {
  return { preset: "", title: "", subject: "", model: "", started: "", fixtures: false, roles: [], status: "running", cost: 0 };
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
    case "saved":
      return { ...s, runId: e.run_id };
    case "replay":
      return { ...s, replayOf: { runId: e.run_id, createdAt: e.created_at } };
    case "swarm_done":
      return { ...s, status: "done", cost: e.cost, final: { answer: e.answer, unsourced: e.unsourced, grounded: e.grounded, label: e.label, failed: e.failed } };
    case "error":
      return { ...s, status: "error", error: { kind: e.kind, text: e.text } };
    default:
      // token, tool_call, tool_result, usage, notice: all carry their role
      return mapRole(s, e.role, (r) => ({ ...r, turn: reduceTurn(r.turn, e) }));
  }
}
