/** Alert delivery (DLVR): which channels are on, the delivery log, test sends and Telegram pairing. Uncached (`send`). */
import { send } from "./core";
import type { DeliveryChannel, DeliveryPatch, DeliveryPayload, DeliveryRow, TelegramPairCheck, TelegramPairStart } from "./types";

export const deliveryApi = {
  get: () => send<DeliveryPayload>("GET", "/api/delivery"),
  put: (patch: DeliveryPatch) => send<DeliveryPayload>("PUT", "/api/delivery", patch),
  log: (limit = 100) => send<{ deliveries: DeliveryRow[] }>("GET", `/api/delivery/log?limit=${limit}`),
  test: (channel: Exclude<DeliveryChannel, "desktop">) => send<{ results: DeliveryRow[] }>("POST", "/api/delivery/test", { channel }),
  pairStart: () => send<TelegramPairStart>("POST", "/api/delivery/telegram/pair/start", {}),
  pairCheck: () => send<TelegramPairCheck>("POST", "/api/delivery/telegram/pair/check", {}),
};
