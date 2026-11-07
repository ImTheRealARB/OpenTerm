/** The daily brief (BRIEF): the last one, and running one now (optionally delivering it). Uncached (`send`). */
import { send } from "./core";
import type { Brief, DeliveryRow } from "./types";

export const briefApi = {
  get: () => send<{ brief: Brief | null }>("GET", "/api/brief"),
  run: (sendIt: boolean) => send<{ brief: Brief; delivered: DeliveryRow[] | null }>("POST", `/api/brief/run?send=${sendIt ? 1 : 0}`),
};
