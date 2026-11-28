/**
 * Types shared by `gpLayer.ts` (startup side), `scriptLayer.ts` (the lazily loaded controller) and the GP panel.
 * Types only: nothing here is imported at run time, so importing it never pulls the script engine or the controller in.
 */
import type { IChartApi, ISeriesApi, SeriesType } from "lightweight-charts";
import type { ScriptRef } from "../functions/gpArgs";
import type { InputDef } from "../script/index";
import type { BarData, ThemeColors } from "./chartBase";

/** What GP hands the chart layer for `SCRIPT=`. */
export interface ScriptLayerProps {
  items: ScriptRef[];
  /** The chart's symbol (upper case): scripts' alerts name it and a `request` for it is answered from the chart's own bars. */
  symbol: string;
  /** The chart's range (a `request` for another symbol asks for at least this much). */
  range: string;
  /** The bars are SYNTHETIC / fixture data: alerts say so. */
  synthetic: boolean;
  /** Called when a script's status changes (loading finished, an error appeared or cleared, the inputs are known). */
  onReport?: (r: ScriptReport) => void;
}

/** One script's state, by name. `error` is a ready-to-show line ("SCRIPT RSI: ... (LINE 3:7)"), "" when fine. */
export interface ScriptStatus {
  state: "loading" | "ready" | "error";
  error: string;
  title?: string;
  inputs?: InputDef[];
}

export type ScriptReport = Record<string, ScriptStatus>;

/** The bar a live tick carries (what ChartView's `live` just made of the newest bar). */
export interface LiveBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

/** What the controller may ask of the chart layer that owns it (all current-state getters, so nothing goes stale). */
export interface ScriptHost {
  chart(): IChartApi | null;
  main(): ISeriesApi<SeriesType> | null;
  data(): BarData;
  colors(): ThemeColors;
  box(): HTMLDivElement | null;
  props(): ScriptLayerProps | undefined;
  /** Message to the indicator worker. */
  post(msg: unknown): void;
  /** Runs `fn` (series added or removed) and puts the visible range back if the chart moved it. */
  keepRange(fn: () => void): void;
  /** Removes empty panes and sizes the rest (gpLayer's own layout). */
  layoutPanes(chart: IChartApi): void;
  /** Refreshes the `chart.extraSeries` / `chart.panes` gauges. */
  publish(): void;
  /** The script marks changed: re-merge them into the price series' marker plugin. */
  setMarks(marks: { time: number; position: "aboveBar" | "belowBar" | "inBar"; shape: "arrowUp" | "arrowDown" | "circle" | "square"; color: string; text: string }[]): void;
  /** The overlay canvas needs a repaint. */
  repaint(): void;
}
