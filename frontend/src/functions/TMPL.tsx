/**
 * TMPL [NAME]: workspace templates (Long-term investor, Day trader, Macro, India). With a name it applies that template;
 * with none it lists them (J/K move, Enter applies). Replacing a customised workspace asks once: Enter / Y = replace, Esc = keep.
 * The untouched starter layout or a lone HELP panel is replaced without asking.
 */
import { useEffect, useRef, useState } from "react";
import { isReplaceable, TEMPLATES, templateById, templateWorkspace, type Template } from "../gui/templates";
import { registerPanelKeys } from "../keys/panelKeys";
import { applyLayout, workspace } from "../state/workspace";
import type { FunctionProps } from "./registry";
import { listNav } from "./listNav";

export default function TMPL({ panelId, args }: FunctionProps) {
  const [sel, setSel] = useState(0);
  const [confirm, setConfirm] = useState<Template | null>(null);
  const [unknown, setUnknown] = useState<string | null>(null);
  const state = useRef({ sel, confirm });
  state.current = { sel, confirm };

  const request = (t: Template) => {
    if (isReplaceable(workspace.get())) applyLayout(templateWorkspace(t));
    else setConfirm(t);
  };

  const wanted = args[0];
  const done = useRef<string | null>(null);
  useEffect(() => {
    if (!wanted || done.current === wanted) return;
    done.current = wanted;
    const t = templateById(wanted);
    if (!t) setUnknown(wanted.toUpperCase());
    else request(t);
  }, [wanted]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const { sel: i, confirm: c } = state.current;
        if (c) {
          if (e.key === "Enter" || e.key === "y" || e.key === "Y") {
            applyLayout(templateWorkspace(c));
            return true;
          }
          if (e.key === "Escape" || e.key === "n" || e.key === "N") {
            setConfirm(null);
            return true;
          }
          return true;
        }
        const to = listNav(e.key, i, TEMPLATES.length);
        if (to !== null) {
          setSel(to);
          return true;
        }
        if (e.key === "Enter") {
          request(TEMPLATES[i]);
          return true;
        }
        return false;
      }),
    [panelId],
  );

  return (
    <div className="fn" data-testid="tmpl">
      <h2>WORKSPACE TEMPLATES</h2>
      {unknown && <div className="err">NO TEMPLATE {unknown} · CHOOSE ONE BELOW</div>}
      {confirm && (
        <div className="warn" role="alertdialog" aria-label="Replace current panels?" data-testid="tmpl-confirm">
          REPLACE CURRENT PANELS WITH {confirm.label.toUpperCase()}? ENTER OR Y = REPLACE · ESC OR N = KEEP{" "}
          <button type="button" onClick={() => applyLayout(templateWorkspace(confirm))}>Replace</button>{" "}
          <button type="button" onClick={() => setConfirm(null)}>Keep</button>
        </div>
      )}
      <table className="t">
        <tbody>
          {TEMPLATES.map((t, k) => (
            <tr key={t.id} className={k === sel ? "on" : ""} aria-selected={k === sel} onClick={() => { setSel(k); request(t); }}>
              <td className="acc">{k === sel ? ">" : ""}</td>
              <td className="acc">{t.id}</td>
              <td>{t.label}</td>
              <td className="dim">{t.views.map((v) => v.fn).join(" · ")}</td>
              <td className="dim">{t.about}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="dim">J/K MOVE · ENTER APPLIES · TMPL NAME APPLIES DIRECTLY</div>
    </div>
  );
}
