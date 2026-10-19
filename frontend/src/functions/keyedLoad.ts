/**
 * Latest-request-wins guard for panels that fetch for a key (symbol, range...) and can be re-keyed while a request is in
 * flight. `start()` returns an `isCurrent` check: call it before touching state once the answer arrives. `invalidate()`
 * marks every pending request stale (call it from an effect cleanup). Pure, so it is unit-tested in Node.
 */
export function latestOnly() {
  let n = 0;
  return {
    start(): () => boolean {
      const mine = ++n;
      return () => mine === n;
    },
    invalidate(): void {
      n++;
    },
  };
}
