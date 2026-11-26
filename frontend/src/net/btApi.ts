/** Backtesting (BT): templates, strategies, imported bars, stored runs, exports, and the jobs that run and validate them. */
import { ApiError, send } from "./core";
import type { JobRec } from "./jobFrames";
import type {
  BtSynth,
  BtCheck, BtCompare, BtImported, BtRunCard, BtRunFull, BtRunRequest, BtStrategy, BtStrategyCard, BtTemplate,
  BtFwdFull, BtFwdSummary,
} from "./types";
import type { BtOptRequest } from "../bt/optArgs";

export const btApi = {
  templates: () => send<{ templates: BtTemplate[] }>("GET", "/api/bt/templates"),
  /** Runs the sandbox rules over the code without saving it (the editor's live check). */
  check: (code: string) => send<BtCheck>("POST", "/api/bt/check", { code }),
  strategies: () => send<{ strategies: BtStrategyCard[] }>("GET", "/api/bt/strategies"),
  strategy: (name: string) => send<BtStrategy>("GET", `/api/bt/strategies/${encodeURIComponent(name)}`),
  /** Python code, or a rule. The server checks both (the sandbox allowlist for code) and says why it refuses. */
  putStrategy: (name: string, body: { code: string } | { rule: string }) =>
    send<BtStrategyCard>("PUT", `/api/bt/strategies/${encodeURIComponent(name)}`, body),
  deleteStrategy: (name: string) => send<{ deleted: string }>("DELETE", `/api/bt/strategies/${encodeURIComponent(name)}`),
  imports: () => send<{ symbols: BtImported[] }>("GET", "/api/bt/import"),
  deleteImport: (symbol: string) => send<{ deleted: string }>("DELETE", `/api/bt/import/${encodeURIComponent(symbol)}`),
  /** Stores the CSV text as the symbol's daily bars (replaces an earlier import). */
  importBars: async (symbol: string, csv: string, tz?: string): Promise<BtImported & { volume: boolean; interval?: string }> => {
    let res: Response;
    const zone = tz ? `&tz=${encodeURIComponent(tz)}` : ""; // Phase 22: the zone of intraday times written without an offset
    try {
      res = await fetch(`/api/bt/import?symbol=${encodeURIComponent(symbol)}${zone}`, { method: "POST", headers: { "Content-Type": "text/plain" }, body: csv });
    } catch {
      throw new ApiError(0, "BACKEND DOWN");
    }
    const json = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail);
    return json;
  },
  /** Phase 22 stored synthetic symbols: `IMPORT SYNTH NAME = AAPL/MSFT`. */
  synthList: () => send<{ synth: BtSynth[] }>("GET", "/api/bt/synth"),
  synthPut: (name: string, formula: string) => send<BtSynth>("POST", "/api/bt/synth", { name, formula }),
  synthDelete: (name: string) => send<{ deleted: string }>("DELETE", `/api/bt/synth/${encodeURIComponent(name)}`),
  runs: () => send<{ runs: BtRunCard[] }>("GET", "/api/bt/runs"),
  compare: (a: string, b: string) => send<BtCompare>("GET", `/api/bt/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
  /** The server-built export: a CSV part (`trades`, `equity`, `metrics`) or the Pine Script of a rule run. */
  exportText: async (id: string, fmt: "csv" | "pine" | "mql5", part = "trades"): Promise<string> => {
    let res: Response;
    try {
      res = await fetch(`/api/bt/runs/${encodeURIComponent(id)}/export?fmt=${fmt}&part=${part}`);
    } catch {
      throw new ApiError(0, "BACKEND DOWN");
    }
    if (!res.ok) {
      const json = await res.json().catch(() => null);
      throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail);
    }
    return res.text();
  },
  /** The server-built binary export (PDF report, XLSX workbook). */
  exportBlob: async (id: string, fmt: string): Promise<Blob> => {
    let res: Response;
    try {
      res = await fetch(`/api/bt/runs/${encodeURIComponent(id)}/export?fmt=${fmt}`);
    } catch {
      throw new ApiError(0, "BACKEND DOWN");
    }
    if (!res.ok) {
      const json = await res.json().catch(() => null);
      throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail);
    }
    return res.blob();
  },
  /** Start a Monte Carlo (`mc`) or walk-forward (`wf`) job on a stored run. */
  validate: (id: string, kind: "mc" | "wf", body: Record<string, unknown> = {}) =>
    send<JobRec>("POST", `/api/bt/runs/${encodeURIComponent(id)}/${kind}`, body),
  /** The job, plus the id its run will be stored under (open it at once when the answer is cached). */
  run: (body: BtRunRequest) => send<JobRec & { run_id: string; run?: BtRunFull }>("POST", "/api/bt/run", body),
  get: (id: string) => send<BtRunFull>("GET", `/api/bt/runs/${encodeURIComponent(id)}`),
  /** Phase 26: start an optimisation job (the result arrives as the job's result, see BtOptResult). */
  opt: (body: BtOptRequest) => send<JobRec & { opt_id: string; budget: number }>("POST", "/api/bt/opt", body),
  /** Phase 26 paper forward tests (play money in OpenTerm's own book; nothing reaches a broker). */
  fwdList: () => send<{ tests: BtFwdSummary[] }>("GET", "/api/bt/fwd"),
  fwdCreate: (body: { symbol: string; strategy: string; interval: string; cash?: number }) =>
    send<{ test: BtFwdSummary; job: JobRec }>("POST", "/api/bt/fwd", body),
  fwdGet: (id: string) => send<BtFwdFull>("GET", `/api/bt/fwd/${encodeURIComponent(id)}`),
  fwdStep: (id: string) => send<JobRec>("POST", `/api/bt/fwd/${encodeURIComponent(id)}/step`, {}),
  fwdStop: (id: string) => send<BtFwdSummary>("POST", `/api/bt/fwd/${encodeURIComponent(id)}/stop`, {}),
  fwdDelete: (id: string) => send<{ deleted: string }>("DELETE", `/api/bt/fwd/${encodeURIComponent(id)}`),
};
