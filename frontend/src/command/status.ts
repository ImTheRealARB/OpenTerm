import { createStore } from "../state/store";

export interface StatusMsg {
  text: string;
  kind: "err" | "info";
}

/** One-line message shown in the top bar next to the command line. */
export const statusMsg = createStore<StatusMsg | null>(null);

export const info = (text: string) => statusMsg.set(() => ({ text, kind: "info" }));
export const fail = (text: string) => {
  statusMsg.set(() => ({ text, kind: "err" }));
  return false;
};
