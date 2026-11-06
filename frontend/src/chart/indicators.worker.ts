/// <reference lib="webworker" />
import { computeEach, type IndicatorName, type Series } from "./indicators";
import { handleLibrary, isLibraryMsg } from "./libraryWorker";

interface Req {
  id: number;
  series: Series;
  which: IndicatorName[];
}

self.onmessage = (ev: MessageEvent<Req>) => {
  if (isLibraryMsg(ev.data)) {
    const r = handleLibrary(ev.data);
    (self as unknown as Worker).postMessage(r.msg, r.transfer);
    return;
  }
  const { id, series, which } = ev.data;
  const t0 = performance.now();
  // One group of outputs per requested indicator, so the page can draw each one on its own.
  const parts = computeEach(series, which);
  const buffers = Object.values(parts).flatMap((g) => Object.values(g ?? {}).map((a) => a.buffer));
  (self as unknown as Worker).postMessage({ id, parts, ms: performance.now() - t0 }, buffers);
};
