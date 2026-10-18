/** Chart screenshot providers: a GP panel registers one so `AI CHART` can send the chart it shows to a vision model. */
export interface ChartShot {
  symbol: string;
  range: string;
  /** PNG data URL of the chart canvas, or null when there is no chart yet. */
  shot: () => string | null;
}

const shots = new Map<number, ChartShot>();

export function registerChartShot(panelId: number, s: ChartShot): () => void {
  shots.set(panelId, s);
  return () => {
    if (shots.get(panelId) === s) shots.delete(panelId);
  };
}

/** The most recently registered chart (the one opened last). */
export function latestChartShot(): ChartShot | null {
  let last: ChartShot | null = null;
  for (const s of shots.values()) last = s;
  return last;
}
