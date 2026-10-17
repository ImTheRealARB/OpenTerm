import { useEffect, useRef, useState } from "react";
import { deleteLayout, layoutList, loadLayout, refreshLayouts } from "../command/layouts";
import { prefillCommand } from "../components/CommandLine";
import { registerPanelKeys } from "../keys/panelKeys";
import type { ApiError } from "../net/api";
import { useStore } from "../state/store";
import { workspace } from "../state/workspace";
import type { FunctionProps } from "./registry";

const when = (t: number) => {
  const d = new Date(t * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

/** LAYOUT / MONITOR with no arguments: saved layouts, keyboard driven. */
export default function Layout({ panelId }: FunctionProps) {
  const list = useStore(layoutList, (l) => l);
  const current = useStore(workspace, (s) => s.name);
  const [sel, setSel] = useState(0);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const state = useRef({ list, sel, confirm });
  state.current = { list, sel, confirm };

  const refresh = () =>
    refreshLayouts()
      .then(() => setErr(null))
      .catch((e: ApiError) => setErr(e.message));

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { list: l, sel: i, confirm: c } = state.current;
        const n = l?.length ?? 0;
        const name = l?.[Math.min(i, n - 1)]?.name;
        if (c && e.key !== "Delete" && e.key !== "x") setConfirm(null);
        switch (e.key) {
          case "j":
          case "ArrowDown":
            setSel(Math.min(n - 1, i + 1));
            return true;
          case "k":
          case "ArrowUp":
            setSel(Math.max(0, i - 1));
            return true;
          case "Enter":
            if (name) void loadLayout(name);
            return true;
          case "Delete":
          case "x":
            if (!name) return true;
            if (c === name) {
              setConfirm(null);
              void deleteLayout(name);
            } else setConfirm(name);
            return true;
          case "s":
            prefillCommand("LAYOUT SAVE ");
            return true;
          case "F5":
            void refresh();
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    [panelId],
  );

  if (!list) return <div className={err ? "err" : "dim"}>{err ? `LAYOUTS UNAVAILABLE: ${err}` : "LOADING…"}</div>;
  const i = Math.min(sel, list.length - 1);
  return (
    <div>
      <h2>
        LAYOUTS {err && <span className="err">STALE: {err}</span>}
      </h2>
      {list.length === 0 ? (
        <div className="dim">NO SAVED LAYOUTS. LAYOUT SAVE NAME (OR CTRL+S) SAVES THIS WORKSPACE.</div>
      ) : (
        <table className="t">
          <colgroup>
            <col style={{ width: 20 }} />
            <col style={{ width: 260 }} />
            <col style={{ width: 70 }} />
            <col style={{ width: 140 }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th />
              <th>NAME</th>
              <th className="n">PANELS</th>
              <th>SAVED</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((l, k) => (
              <tr key={l.name} className={k === i ? "on" : ""} aria-selected={k === i}>
                <td className="acc">{k === i ? ">" : ""}</td>
                <td className={l.name === current ? "acc" : ""}>{l.name}</td>
                <td className="n">{l.panels}</td>
                <td className="dim">{when(l.updated_at)}</td>
                <td>
                  {confirm === l.name ? (
                    <span className="err">DELETE? PRESS DEL AGAIN</span>
                  ) : (
                    l.name === current && <span className="dim">CURRENT</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="dim">J K / ↑ ↓ SELECT · ENTER LOAD · DEL DELETE · S SAVE AS · F5 REFRESH · CTRL+S SAVE · CTRL+O OPEN</div>
    </div>
  );
}
