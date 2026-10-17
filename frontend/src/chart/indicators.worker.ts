/// <reference lib="webworker" />
import { compute, type IndicatorName, type Series } from "./indicators";

interface Req {
  id: number;
  series: Series;
  which: IndicatorName[];
}

self.onmessage = (ev: MessageEvent<Req>) => {
  const { id, series, which } = ev.data;
  const t0 = performance.now();
  const results = compute(series, which);
  const buffers = Object.values(results).map((a) => a.buffer);
  (self as unknown as Worker).postMessage({ id, results, ms: performance.now() - t0 }, buffers);
};
