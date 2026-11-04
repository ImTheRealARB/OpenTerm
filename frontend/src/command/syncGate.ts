/**
 * Runs `load` until it has worked once, then never again.
 * Used for command history: if the backend is down at page load the first load fails,
 * and the next time the socket link reports OK we try again (instead of staying empty).
 * Pure (no network imports) so vitest can test it.
 */
export function createSyncGate(load: () => Promise<void>) {
  let done = false;
  let busy = false;

  /** One try. Does nothing if already loaded or a try is running. Never throws. */
  async function attempt(): Promise<void> {
    if (done || busy) return;
    busy = true;
    try {
      await load();
      done = true;
    } catch {
      /* stays not loaded: the next OK link status tries again */
    } finally {
      busy = false;
    }
  }

  return {
    attempt,
    /** Call with every link status change; retries only when the link is OK and nothing was loaded yet. */
    onLink: (status: string): Promise<void> => (status === "OK" ? attempt() : Promise.resolve()),
    loaded: () => done,
  };
}
