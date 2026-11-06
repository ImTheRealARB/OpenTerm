/** API keys (APIKEYS) and the AI spend cap. Uncached (`send`); the backend never returns a key value, only its status. */
import { send } from "./core";
import type { KeyRow, KeysPayload } from "./types";

export const keysApi = {
  keys: () => send<KeysPayload>("GET", "/api/keys"),
  putKey: (name: string, fields: Record<string, string>) => send<KeyRow>("PUT", `/api/keys/${encodeURIComponent(name)}`, { fields }),
  testKey: (name: string) => send<KeyRow>("POST", `/api/keys/${encodeURIComponent(name)}/test`),
  deleteKey: (name: string) => send<KeyRow>("DELETE", `/api/keys/${encodeURIComponent(name)}`),
  putLlmCap: (cap: number) => send<KeysPayload["spend"]>("PUT", "/api/llm/cap", { cap }),
};
