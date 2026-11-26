/**
 * "Latest request wins": hand out a ticket per request, and only the newest ticket is current.
 * A slow older response checks `isCurrent(ticket)` before it writes, so it cannot overwrite the
 * result of a newer request (audit H-30: a second SWARM run's state was overwritten by the
 * aborted first run's late INCOMPLETE write).
 */
export function latestOnly() {
  let n = 0;
  return {
    next: (): number => ++n,
    isCurrent: (ticket: number): boolean => ticket === n,
  };
}
