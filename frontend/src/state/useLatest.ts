import { useRef } from "react";

/**
 * A ref that always holds the latest value.
 * Why: a key handler registered once per mount (a `useEffect` with stable deps) would otherwise keep reading the
 * render it was created in. Reading `latest.current` inside the handler always gives the current state.
 */
export function useLatest<T>(value: T) {
  const r = useRef(value);
  r.current = value;
  return r;
}
