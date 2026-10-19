/**
 * Socket liveness check, pure (no window): a half-open TCP connection never fires `close`, so without this the
 * status bar would say BACKEND OK forever while no data arrives. Times are performance.now() values.
 */

/** Ping intervals in a row with no message at all after the ping before the socket is treated as dead. */
export const MAX_MISSED = 2;

/**
 * Called when the next ping is due. `lastPingAt` = when the previous ping went out (0 = none yet), `lastRecvAt` =
 * when the last message of any kind arrived. Returns the new missed count (0 when anything arrived since that ping).
 */
export function heartbeatMissed(missed: number, lastPingAt: number, lastRecvAt: number): number {
  if (!lastPingAt) return 0;
  return lastRecvAt >= lastPingAt ? 0 : missed + 1;
}

export const heartbeatDead = (missed: number): boolean => missed >= MAX_MISSED;
