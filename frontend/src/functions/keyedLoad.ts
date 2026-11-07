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

/**
 * Key guard for loaders that fetch one thing per key (a symbol, a query, a page). `set(key)` records the key the panel
 * shows NOW; `isCurrent(k)` says whether an answer that was asked for key `k` is still wanted. An answer for an old key
 * that lands after the key changed is dropped. (Unlike `latestOnly`, two answers for the SAME key both count, which is
 * what F5 and the auto refresh need.) Pure, so it is unit-tested in Node.
 */
export function keyGate(initial: string) {
  let current = initial;
  return {
    set(key: string): void {
      current = key;
    },
    isCurrent(key: string): boolean {
      return current === key;
    },
  };
}
