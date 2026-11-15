/** Backend side of settings: reconcile once after the first paint, then store each edit (debounced). */
import { info } from "../command/status";
import { settingsApi } from "../net/settingsApi";
import { mergeRemote, pushPayload, setLocalChangeListener } from "./runtime";

const PUSH_DELAY_MS = 300;
let timer = 0;
let pushing: Promise<void> | null = null;

async function push(): Promise<void> {
  const { settings, fieldTimes } = pushPayload();
  try {
    // The answer is the merged document: fields another device changed later than ours come back and are merged in. An edit made while
    // the request was in flight stays dirty (it is newer than the answer) and its own push is already scheduled.
    mergeRemote(await settingsApi.put(settings, fieldTimes));
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
  if (mergeRemote(remote)) schedule(); // we hold a change the backend lacks
}
