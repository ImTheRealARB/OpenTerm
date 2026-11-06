/** Kite Connect (read-only data source). Login is `/api/kite/login`, opened in a new tab; the api key never reaches this app. */
import { send } from "./core";
import type { KiteStatus } from "./types";

export const kiteApi = {
  loginUrl: "/api/kite/login",
  status: () => send<KiteStatus>("GET", "/api/kite/status"),
  logout: () => send<KiteStatus>("POST", "/api/kite/logout"),
};
