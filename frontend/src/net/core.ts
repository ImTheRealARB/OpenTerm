/**
 * The request layer every client in net/ is built on. Same-key GETs share one fetch, and answers are cached briefly
 * so panels and prefetch reuse them. Every payload keeps the backend's source/as_of/stale envelope intact.
 *
 * Why it is split from the payload types (`types.ts`): this file imports `perf/metrics`, which needs a browser, so vitest
 * cannot load it. Pure modules import only the types.
 */
import { gauges } from "../perf/metrics";
import { keyRequired, type KeyRequiredInfo } from "./keyRequired";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public kind = "unavailable",
    /** Each provider's reason, e.g. "gdelt: rate_limited (429 from upstream)". */
    public detail?: string,
    /** Phase 11: the missing key's env name on a 424 KEY REQUIRED envelope (see keyRequired.ts). */
    public key?: string,
    /** Phase 12: 0-based column of a BT rule syntax error. */
    public col?: number,
  ) {
    super(message);
  }
}

/** The key and message of a KEY REQUIRED failure, or null for any other error. */
export function keyRequiredOf(e: ApiError | null | undefined): KeyRequiredInfo | null {
  return e ? keyRequired(e.status, { key: e.key, detail: e.detail }) : null;
}

const MAX_ENTRIES = 500;
const cache = new Map<string, { value: unknown; at: number }>();
const inflight = new Map<string, Promise<unknown>>();

/** GET that shares one in-flight fetch per path and keeps the answer for `maxAgeMs` (0 = always ask the server). */
async function request<T>(path: string, maxAgeMs: number): Promise<T> {
  const hit = cache.get(path);
  if (hit && performance.now() - hit.at < maxAgeMs) return hit.value as T;
  const pending = inflight.get(path);
  if (pending) return pending as Promise<T>;

  const t0 = performance.now();
  const p = (async () => {
    let res: Response;
    try {
      res = await fetch(path);
    } catch {
      throw new ApiError(0, "BACKEND DOWN");
    }
    const body = await res.json().catch(() => null);
    gauges.set(`api.${path.split("?")[0]}`, performance.now() - t0);
    if (!res.ok) throw new ApiError(res.status, body?.error ?? `HTTP ${res.status}`, body?.kind, body?.detail, body?.key);
    cache.delete(path);
    cache.set(path, { value: body, at: performance.now() });
    if (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value!);
    return body as T;
  })();
  inflight.set(path, p);
  try {
    return await p;
  } finally {
    inflight.delete(path);
  }
}

/** Uncached write (or read that must be fresh). Errors carry the backend's message. */
export async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "BACKEND DOWN");
  }
  const json = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail, json?.key, json?.col);
  return json as T;
}

/** What `sendRaw` returns: the HTTP outcome and the parsed JSON body (null when the body was not JSON). */
export interface RawReply<T> {
  ok: boolean;
  status: number;
  json: T | null;
}

/**
 * Like `send`, but an HTTP error is NOT thrown: the caller gets `{ ok, status, json }` and words the error itself.
 * For panels that show their own text per status (AI documents, SWARM, THESIS, AUDIT). Only a network failure throws
 * (`ApiError` 0, "BACKEND DOWN"). Pass `json` for a JSON body, or `body` + `contentType` for something else (a file).
 * Non-GET requests always carry a Content-Type, as the backend's Origin guard expects for bodies.
 */
export async function sendRaw<T = unknown>(
  method: string,
  path: string,
  opts: { json?: unknown; body?: BodyInit; contentType?: string } = {},
): Promise<RawReply<T>> {
  const { json, body, contentType } = opts;
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: method === "GET" ? undefined : { "Content-Type": contentType ?? "application/json" },
      body: body ?? (json === undefined ? undefined : JSON.stringify(json)),
    });
  } catch {
    throw new ApiError(0, "BACKEND DOWN");
  }
  return { ok: res.ok, status: res.status, json: await res.json().catch(() => null) };
}

/** Query string from a map, leaving out empty values. */
export const qs = (o: Record<string, string | undefined>) =>
  new URLSearchParams(Object.entries(o).filter((e): e is [string, string] => !!e[1])).toString();

/**
 * How long (ms) this client keeps a GET answer before asking again. The backend has its own cache behind it, so these are
 * short; named by duration so a TTL in a client reads at a glance (`TTL.m5` = five minutes). Each endpoint keeps the TTL it had.
 */
export const TTL = {
  s1: 1_000,
  s2: 2_000,
  s4: 4_000,
  s15: 15_000,
  s20: 20_000,
  s30: 30_000,
  m1: 60_000,
  m2: 120_000,
  m3: 180_000,
  m5: 300_000,
  m10: 600_000,
  h1: 3_600_000,
} as const;

/**
 * Cached GET: the one place a client builds `path?query`, picks the cache lifetime and calls `request`.
 * `params` adds `?` + the query string (empty values dropped; omit `params` for a path with no query).
 * `fresh` (F5 in a panel) skips this client's cache for this call (the backend still serves its own cached envelope).
 * Use `send("GET", ...)` instead for reads that must never be cached (layouts, watchlists, jobs).
 */
export function get<T>(path: string, params: Record<string, string | undefined> | undefined, ttlMs: number, fresh = false): Promise<T> {
  const url = params === undefined ? path : `${path}?${qs(params)}`;
  return request<T>(url, fresh ? 0 : ttlMs);
}
