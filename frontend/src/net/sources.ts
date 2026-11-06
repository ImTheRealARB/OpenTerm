import { gauges } from "../perf/metrics";
import { createStore } from "../state/store";
import { systemApi } from "./systemApi";
import type { SourcesPayload } from "./types";

/** Provider health for the status bar, polled slowly; the SOURCES screen polls faster on its own. */
export const sources = createStore<SourcesPayload | null>(null);

export function pollSources(intervalMs = 10_000): void {
  const tick = async () => {
    try {
      const s = await systemApi.sources();
      sources.set(() => s);
      if (s.cache.hit_pct != null) gauges.set("cache.hitPct", s.cache.hit_pct);
      for (const p of s.providers) {
        if (p.latency_p50_ms != null) gauges.set(`provider.${p.name}`, p.latency_p50_ms);
      }
    } catch {
      sources.set(() => null);
    }
  };
  void tick();
  setInterval(tick, intervalMs);
}
