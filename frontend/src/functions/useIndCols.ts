/** WL / Q indicator columns: starts a `scan.cols` task for the grid's symbols and returns the extra grid columns plus a
 * header note. The task restarts only when the column list or the symbol list changes (not on every tick). */
import { useMemo } from "react";
import type { Column } from "../components/Grid";
import { scanApi } from "../net/scanApi";
import { colsNote, indColumns } from "./indCols";
import { useTaskPoll } from "./useTaskPoll";

export function useIndCols<R extends { symbol: string }>(symbols: string[], cols: string | null): { columns: Column<R>[]; note: string; failed: boolean } {
  const list = symbols.join(",");
  const key = cols && list ? `${cols}|${list}` : null;
  const { task, error } = useTaskPoll(key ? () => scanApi.cols(list.split(","), cols ?? "") : null, scanApi.colsTask, key);
  const res = task?.state === "done" ? task.result : null;
  const err = error ?? (task?.state === "error" ? task.error : null);
  const columns = useMemo(() => indColumns<R>(res, cols), [res, cols]);
  const note = colsNote(cols, { error: err, done: task?.done ?? 0, total: task?.total ?? 0, res });
  return { columns, note, failed: !!err };
}
