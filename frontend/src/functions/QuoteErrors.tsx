import { PanelNote } from "../components/PanelNote";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import type { QRow } from "./quoteRows";

/**
 * GUI mode only (Terminal returns null, so it is unchanged): ONE plain line above a quote grid when some rows failed.
 * The per-row text (e.g. "PROVIDER DOWN") stays in the grid; this says how many, what it means and offers Retry.
 * Pure wording lives in `quoteErrorSummary` so it is unit-tested.
 */
export function quoteErrorSummary(rows: Pick<QRow, "symbol" | "error">[]): { text: string; plain: string } | null {
  const bad = rows.filter((r) => r.error);
  if (!bad.length) return null;
  const kinds = [...new Set(bad.map((r) => r.error!))];
  const names = bad.slice(0, 4).map((r) => r.symbol).join(", ") + (bad.length > 4 ? "…" : "");
  const text = `ERR: ${kinds.join(" / ")} (${bad.length} of ${rows.length}: ${names})`;
  const allDown = kinds.every((k) => /PROVIDER DOWN|TIMEOUT|UNREACHABLE|ERR/i.test(k) && !/NO DATA/i.test(k));
  const plain = allDown
    ? `The data source isn't answering for ${bad.length} ${bad.length === 1 ? "name" : "names"}. The others loaded. It retries on its own, or press Retry.`
    : `The data source has no quote for ${bad.length} ${bad.length === 1 ? "name" : "names"}. Check the symbol, or press Retry in case it was a hiccup.`;
  return { text, plain };
}

export function QuoteErrors({ rows, onRetry }: { rows: Pick<QRow, "symbol" | "error">[]; onRetry: () => void }) {
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const sum = gui ? quoteErrorSummary(rows) : null;
  if (!sum) return null;
  return (
    <PanelNote kind="error" plain={sum.plain} onRetry={onRetry}>
      {sum.text}
    </PanelNote>
  );
}
