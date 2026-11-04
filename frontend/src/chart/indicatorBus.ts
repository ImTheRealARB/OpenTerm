/**
 * Tiny bus between the IND library panel and a chart. The panel calls `requestIndicator`; a chart (GP) registers a listener
 * with `onIndicatorRequest` and returns true when it took the request. No listener, or none answering true, means "open a chart first".
 */
export type IndicatorRequest = { id: string; params?: number[]; label?: string } | { formula: string; label?: string };

type Listener = (req: IndicatorRequest) => boolean | void;

const listeners = new Set<Listener>();

export function onIndicatorRequest(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** True if at least one chart answered. */
export function requestIndicator(req: IndicatorRequest): boolean {
  let answered = false;
  for (const fn of [...listeners]) if (fn(req) === true) answered = true;
  return answered;
}

export function listenerCount(): number {
  return listeners.size;
}
