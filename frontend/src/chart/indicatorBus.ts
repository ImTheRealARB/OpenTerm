/**
 * Tiny bus between the IND library panel and a chart. The panel calls `requestIndicator`; a chart (GP) registers a listener
 * with `onIndicatorRequest` and returns true when it took the request. No listener, or none answering true, means "open a chart first".
 */
import { formulaInd, libraryInd } from "../functions/gpArgs";

/** `op`: "add" (default; a preset load never removes what is already there) or "toggle" (Enter in IND: ON becomes OFF). */
export type IndicatorRequest = ({ id: string; params?: number[] } | { formula: string }) & { label?: string; op?: "add" | "toggle" };

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

/** The key of a request on the chart (`LIB:ATR:14`, `F:<encoded formula>`), same as GP's args tokens. */
export function requestKey(req: IndicatorRequest): string {
  return "formula" in req ? formulaInd(req.formula).key : libraryInd(req.id, req.params ?? []).key;
}

// Which library / formula entries the answering chart shows now, so IND can mark them ON and Enter toggles them off.
let onChart: readonly string[] = [];
const chartListeners = new Set<() => void>();

export function setChartIndicators(keys: readonly string[]): void {
  if (keys.length === onChart.length && keys.every((k, i) => k === onChart[i])) return;
  onChart = keys;
  chartListeners.forEach((l) => l());
}
export const getChartIndicators = (): readonly string[] => onChart;
export function onChartIndicators(fn: () => void): () => void {
  chartListeners.add(fn);
  return () => {
    chartListeners.delete(fn);
  };
}
