/**
 * Retry for the "alert fired" report to the backend. Alerts are evaluated in the browser, but email / Telegram / webhook
 * delivery starts only when the backend hears about the trigger. So a single failed POST (backend restarting, 5xx,
 * network blip) must not be the end: we keep trying, with growing waits, for as long as the caller says the alert is
 * still in its "firing" state. Pure (no DOM, no network) so vitest can run it with fake timers.
 */

/** Wait before retry number `attempt` (1 = first retry): 2 s, 5 s, 15 s, 30 s, then every 60 s. */
export function retryDelayMs(attempt: number): number {
  const steps = [2_000, 5_000, 15_000, 30_000];
  return attempt <= steps.length ? steps[attempt - 1] : 60_000;
}

export interface RetryOptions {
  /** False once the alert was deleted or re-armed: nothing left to report, stop. */
  stillWanted: () => boolean;
  /** The backend accepted the report. */
  onDone: () => void;
  /** An attempt failed (called each time, with the 1-based attempt number). */
  onFail: (error: unknown, attempt: number) => void;
}

/**
 * Sends once now; on failure schedules another send. Never runs two sends at once and stops after the first success,
 * so the backend gets at most one accepted report (the caller keeps the id in its `firing` set meanwhile, which keeps
 * the tick evaluator from firing the same alert again).
 */
export function sendWithRetry(send: () => Promise<unknown>, o: RetryOptions): void {
  let attempt = 0;
  const run = (): void => {
    send().then(
      () => o.onDone(),
      (e) => {
        attempt++;
        o.onFail(e, attempt);
        if (o.stillWanted()) setTimeout(() => { if (o.stillWanted()) run(); }, retryDelayMs(attempt));
      },
    );
  };
  run();
}
