import { useEffect, useMemo, useRef, useState } from "react";
import { execute } from "../command/execute";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { ALIASES } from "./aliases";
import { CATEGORY_OF } from "./categories";
import { buildRows, filterRows, type DirRow } from "./funcDirectory";
import { FUNCTION_LIST } from "./registry";
import { useLatest } from "../state/useLatest";

/**
 * FUNC: the function directory. Every function code with its one-line purpose.
 * Type letters to filter, arrows move, Enter opens the code (same as typing it), Esc clears the filter.
 * Digits are left alone so number-select works here too: "3" then Enter opens the third row of the list.
 */
const COLUMNS: Column<DirRow>[] = [
  { title: "CODE", width: 10, text: (r) => r.code, color: (r) => (r.aliasOf ? "dim" : "acc") },
  { title: "PURPOSE", width: 78, text: (r) => r.purpose },
  { title: "TAKES", width: 6, text: (r) => r.takes, color: () => "dim" },
  { title: "GUI MENU", width: 10, text: (r) => r.category, color: () => "dim" },
];

export default function FUNC({ panelId }: { panelId: number }) {
  const grid = useRef<GridHandle>(null);
  const [filter, setFilter] = useState("");
  // The registry is static, so the full list is built once.
  const all = useMemo(
    () =>
      buildRows(
        FUNCTION_LIST,
        ALIASES,
        (c) => CATEGORY_OF[c],
      ),
    [],
  );
  const rows = useMemo(() => filterRows(all, filter), [all, filter]);
  const latest = useLatest({ rows, filter });

  // A new filter puts the cursor back on the best match.
  useEffect(() => {
    grid.current?.moveTo(0);
  }, [filter]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, filter: f } = latest.current;
        switch (e.key) {
          case "ArrowDown":
            g?.move(1);
            return true;
          case "ArrowUp":
            g?.move(-1);
            return true;
          case "PageDown":
            g?.page(1);
            return true;
          case "PageUp":
            g?.page(-1);
            return true;
          case "Home":
            g?.moveTo(0);
            return true;
          case "End":
            g?.moveTo(cur.length - 1);
            return true;
          case "Enter": {
            const r = cur[g?.selected() ?? 0];
            if (r) execute(r.code); // like typing the code; a function that needs a security says so in the status line
            return true;
          }
          case "Backspace":
            if (!f) return false;
            setFilter(f.slice(0, -1));
            return true;
          case "Escape":
            if (!f) return false; // nothing to clear: Esc keeps its normal job
            setFilter("");
            return true;
        }
        // Letters build the filter (not "/", which is the command-line key; not digits, which are number-select).
        if (/^[a-zA-Z]$/.test(e.key)) {
          setFilter(f + e.key.toUpperCase());
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">FUNCTION DIRECTORY</span>
        <span> · FILTER: {filter || "(TYPE LETTERS)"}</span>
        <span className="dim"> · {rows.length} OF {all.length}</span>
        <span className="dim legend"> · ↑↓ MOVE · ENTER OPEN · BKSP/ESC CLEAR · NUMBER+ENTER OPENS THAT ROW</span>
      </div>
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
