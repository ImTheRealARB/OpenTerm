/** Third-party extensions (EXT): the list, the enable switch, and an enabled extension's table or series route. */
import type { ExtInfo, ExtPayload } from "../functions/extPayload";
import { get, send, TTL } from "./core";
import type { Envelope } from "./types";

export interface ExtList {
  extensions: ExtInfo[];
  dir: string | null;
  /** The permissions notice (third-party code, runs with your permissions). */
  notice: string;
}

export const extApi = {
  list: () => get<ExtList>("/api/ext", undefined, 0, true),
  enable: (name: string) => send<{ extension: ExtInfo; notice: string }>("POST", `/api/ext/${encodeURIComponent(name)}/enable`),
  disable: (name: string) => send<{ extension: ExtInfo }>("POST", `/api/ext/${encodeURIComponent(name)}/disable`),
  data: (name: string, route: string, args: string[], fresh = false) =>
    get<Envelope<ExtPayload>>(`/api/ext/${encodeURIComponent(name)}/${encodeURIComponent(route)}`, { q: args.join(" ") || undefined }, TTL.s30, fresh),
};

