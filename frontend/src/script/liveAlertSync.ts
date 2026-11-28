/**
 * Live script alerts: loading the stored list and deleting an alert. Small on purpose: the startup code reaches it with
 * `import()` (one tiny chunk), and it loads the runner (`liveAlerts.ts`, which brings the script engine) ONLY when the list is
 * not empty, so a user with no script alerts never downloads the engine for this.
 */
import { parseScriptAlertCmd } from "../command/scriptAlertArgs";
import { fail, info } from "../command/status";
import type { SecurityRef } from "../command/markets";
import { errMessage } from "../net/errText";
import { scriptsApi } from "../net/scriptsApi";
import { scriptAlerts, scriptAlertsError } from "./liveAlertState";

/** Set once the runner chunk has loaded: from then on every refresh syncs it, even to an empty list (it must stop removed alerts). */
let runner: typeof import("./liveAlerts") | null = null;

/**
 * Reads the stored list into `scriptAlerts` and hands it to the runner. A failed read keeps the last good list and says why in
 * `scriptAlertsError` (ALRT shows it as its own line): nothing is guessed.
 */
export async function refreshScriptAlerts(): Promise<void> {
  try {
    const { alerts } = await scriptsApi.alerts();
    scriptAlerts.set(() => alerts);
    scriptAlertsError.set(() => null);
  } catch (e) {
    scriptAlertsError.set(() => errMessage(e));
    return;
  }
  const list = scriptAlerts.get() ?? [];
  if (!runner && list.length) {
    try {
      runner = await import("./liveAlerts");
    } catch (e) {
      scriptAlertsError.set(() => `SCRIPT ALERTS NOT RUNNING: ${errMessage(e)}`); // the chunk did not load: said, not swallowed
      return;
    }
  }
  runner?.syncRunners(list);
}

/**
 * Runs an `ALRT` command that `alerts.ts` saw is a script-alert form (`ALRT SYM SCRIPT=NAME [COND="title"]`, `ALRT DEL SC<id>`).
 * Reading it lives here, not in `alerts.ts`, so the parser stays out of the startup bundle. A create goes on to the runner
 * module (it checks the script with the engine before saving). Every failure is said on the status line.
 */
export async function scriptAlertCommand(args: string[], security?: SecurityRef): Promise<boolean> {
  const c = parseScriptAlertCmd(args, security);
  if (!c) return fail("NOT A SCRIPT ALERT: ALRT SYM SCRIPT=NAME [COND=\"TITLE\"]");
  if (c.kind === "error") return fail(c.message);
  if (c.kind === "deleteScript") return deleteScriptAlert(c.id);
  return (await import("./liveAlerts")).createScriptAlert(c);
}

/** `ALRT DEL SC<id>`. */
export async function deleteScriptAlert(id: number): Promise<boolean> {
  try {
    await scriptsApi.removeAlert(id);
  } catch (e) {
    return fail(`SCRIPT ALERT SC${id} NOT DELETED: ${errMessage(e)}`);
  }
  info(`SCRIPT ALERT SC${id} DELETED`);
  await refreshScriptAlerts();
  return true;
}
