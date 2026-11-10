/**
 * The AI layer's client: streamed answers (AI chat, AI BT / CHART / AUTO / FILING, SWARM), document loading, stored SWARM runs,
 * the audit ledger and theses. Model output is never cached, so every call here is uncached; errors come back as `RawReply`
 * (the panels word them) rather than thrown, except a network failure ("BACKEND DOWN").
 */
import { sendRaw } from "./core";
import { parseSse } from "./sse";

/** The event `streamPost` makes up when the server refuses the request, so a panel shows it like any other stream error. */
export interface SseHttpError {
  type: "error";
  kind: string;
  text: string;
}

/**
 * POST `body` as JSON and hand each server-sent event to `onEvent` as it arrives.
 *
 * Returns `true` when the stream ran to its end, `false` when the server refused (non-2xx or no body): the refusal is
 * delivered to `onEvent` as an `error` event with the server's own kind and text (`HTTP <status>` if it sent none).
 * Throws on a network failure, on a read failure mid-stream, and with an `AbortError` when `signal` is aborted: the caller
 * decides what each means for its own state (INCOMPLETE, BACKEND DOWN). If the stream ends without a closing event the
 * caller is the one who knows what "closing" is, so it checks that after a `true`.
 * `body` may be `undefined` (a replay URL needs none).
 */
export async function streamPost<E>(url: string, body: unknown, signal: AbortSignal, onEvent: (e: E) => void): Promise<boolean> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const j = await res.json().catch(() => null);
    const refused: SseHttpError = { type: "error", kind: j?.kind ?? "http", text: j?.error ?? `HTTP ${res.status}` };
    onEvent(refused as unknown as E); // every stream's event union has this exact error shape
    return false;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  // Network chunks do not line up with events: keep the unfinished tail and prepend it to the next chunk.
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return true;
    buf += dec.decode(value, { stream: true });
    const parsed = parseSse<E>(buf);
    buf = parsed.rest;
    parsed.events.forEach(onEvent);
  }
}

/** True for the error `fetch` throws when its AbortController was aborted (a user pressing Esc, a panel closing). */
export const isAbort = (e: unknown) => (e as Error).name === "AbortError";

export const aiApi = {
  /** Spend today and the cap; the AI header reads `json.spend`. */
  health: <T>() => sendRaw<T>("GET", "/api/llm/health"),
  /** Fetches a filing from SEC and keeps its text as the AI document. */
  loadFiling: <T>(symbol: string, form: string) => sendRaw<T>("POST", "/api/ai/doc/filing", { json: { symbol, form } }),
  /** Reads an uploaded file (PDF, text) as the AI document. */
  uploadDoc: <T>(file: File) =>
    sendRaw<T>("POST", `/api/ai/doc/upload?name=${encodeURIComponent(file.name)}`, { body: file, contentType: "application/octet-stream" }),
  swarmPresets: <T>() => sendRaw<T>("GET", "/api/ai/swarm/presets"),
  swarmRuns: <T>() => sendRaw<T>("GET", "/api/ai/runs?kind=swarm"),
  ledger: <T>() => sendRaw<T>("GET", "/api/ai/ledger?limit=100"),
  /** Stored (redacted) question and answer of one entry; 404 when none is stored. */
  ledgerText: <T>(seq: number) => sendRaw<T>("GET", `/api/ai/ledger/${seq}/text`),
  /** Deletes stored text: one entry (`seq`) or all (null). The hash chain is not touched. */
  purgeLedgerText: <T>(seq: number | null) => sendRaw<T>("POST", "/api/ai/ledger/purge-text", { json: seq === null ? {} : { seq } }),
  ledgerVerify: <T>() => sendRaw<T>("GET", "/api/ai/ledger/verify"),
  /** Theses, all or for one symbol. */
  theses: <T>(symbol: string | null) => sendRaw<T>("GET", `/api/theses${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`),
  createThesis: <T>(body: unknown) => sendRaw<T>("POST", "/api/theses", { json: body }),
  /** One thesis: PATCH a field, or DELETE it. `path` is `/api/theses/<id>`. */
  thesisCall: <T>(method: string, path: string, body?: unknown) => sendRaw<T>(method, path, { json: body }),
};
