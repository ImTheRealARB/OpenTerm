/** Backend side of settings: reconcile once after the first paint, then store each edit (debounced). */
import { info } from "../command/status";
import { settingsApi } from "../net/settingsApi";
import { adoptRemote, markSynced, mirrorState, setLocalChangeListener } from "./runtime";
import { reconcile } from "./schema";

const PUSH_DELAY_MS = 300;
let timer = 0;
let pushing: Promise<void> | null = null;

async function push(): Promise<void> {
  const sent = JSON.stringify(mirrorState().settings);
  try {
    const doc = await settingsApi.put(JSON.parse(sent));
    markSynced(sent, doc.updated_at);
  } catch (e) {
    // Backend down or rejected: the local mirror keeps the change (dirty) and is retried at next start.
    const msg = (e as Error).message;
    if (!/BACKEND DOWN/.test(msg)) info(`SETTINGS NOT SAVED ON THE SERVER: ${msg}`);
  }
}

function schedule(): void {
  clearTimeout(timer);
  timer = window.setTimeout(() => {
    pushing = (pushing ?? Promise.resolve()).then(push);
  }, PUSH_DELAY_MS);
}

export async function startSettingsSync(): Promise<void> {
  setLocalChangeListener(schedule);
  let remote;
  try {
    remote = await settingsApi.get();
  } catch {
    return; // backend down: keep the mirror, push on the next edit or start
  }
  const m = mirrorState();
  const decision = reconcile(m, remote);
  if (decision === "push") schedule();
  else if (decision === "adopt") adoptRemote(remote.settings ?? {}, remote.updated_at ?? 0);
}
