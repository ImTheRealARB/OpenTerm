import "./HelpDrawer.css"; // this component's GUI-only rules, loaded with its chunk
import { useEffect, useRef } from "react";
import { FN_INFO, runItem } from "../components/windowMenuRun";
import { menuItems } from "../components/windowMenu";
import { categoryOf } from "../functions/categories";
import { FUNCTIONS } from "../functions/registry";
import { effectiveBindings, type Action } from "../keys/keys";
import { purposeOf } from "./purposes";
import { currentView, workspace } from "../state/workspace";
import { useStore } from "../state/store";
import { chromeKeyDown, focusCommandLine } from "./chrome";
import { closeHelp, helpDrawer } from "./helpState";
import { TOOLBARS } from "./toolbars";

/**
 * Right-hand drawer that explains the focused panel's function: what it is, how to type it, its buttons and keys, and
 * the functions related to it. Everything comes from data that already exists (the registry, `toolbars.ts`, the
 * RELATED list of the window menu), so it can never drift from what the panel really does.
 *
 * Esc closes it and gives focus back to whatever had it before (the "?" button, or the command line).
 */
/** Keys every panel has, with the action name whose live binding is shown. */
const GLOBAL_KEYS: readonly (readonly [Action, string])[] = [
  ["refresh", "Refresh"],
  ["exportCsv", "Export the table as CSV (also E in tables)"],
  ["windowMenu", "Window menu: recent, related, options"],
  ["helpDrawer", "This help drawer"],
];

export function HelpDrawer() {
  const state = useStore(helpDrawer, (s) => s);
  const panel = useStore(workspace, (s) => (state ? s.panels[state.panel] : undefined));
  const root = useRef<HTMLElement>(null);

  // Opening moves focus into the drawer, so Esc (and Tab to its buttons) work at once.
  useEffect(() => {
    if (state) root.current?.focus();
  }, [state]);

  // Switching to terminal mode unmounts this component: forget the open drawer so it is not back when GUI returns.
  useEffect(() => () => helpDrawer.set(() => null), []);

  if (!state || !panel) return null;
  const view = currentView(panel);
  const def = view.fn ? FUNCTIONS.get(view.fn) : undefined;
  const buttons = view.fn ? (TOOLBARS[view.fn] ?? []) : [];
  const keys = effectiveBindings();
  const related = menuItems(1, panel, FN_INFO).flatMap((it) => (it.kind === "fn" ? [it] : []));

  return (
    <aside
      ref={root}
      className="hd"
      data-testid="help-drawer"
      role="complementary"
      aria-label="Help for the focused panel"
      tabIndex={-1}
      onKeyDown={(e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return; // chords (Alt+H closes it too) bubble to the global handler
        if (e.key === "Escape") {
          e.stopPropagation();
          e.preventDefault();
          closeHelp();
          return;
        }
        chromeKeyDown(e); // everything else stays inside the drawer (Tab and Enter still work normally)
      }}
    >
      <div className="hd-top">
        <span className="hd-h">HELP · PANEL {panel.id}</span>
        <span className="pt-sp" />
        <button type="button" className="pt-b" data-testid="help-close" onClick={closeHelp}>
          Close (Esc)
        </button>
      </div>
      {!def || !view.fn ? (
        <div className="hd-body">
          <div className="hd-t">Empty panel</div>
          <p>Nothing is open in this panel. Pick a function from the menu bar or the sidebar, or type a command such as AAPL GP on the command line.</p>
        </div>
      ) : (
        <div className="hd-body">
          <div className="hd-t" data-testid="help-title">
            <span className="hd-code">{def.code}</span> {def.title}
          </div>
          {/* 1. what the panel is for, in one sentence */}
          <p className="hd-purpose" data-testid="help-purpose">{purposeOf(def.code, def.title)}</p>
          <div className="dim">Category: {categoryOf(def.code)}</div>
          {/* 2. its buttons (the row under the title bar) */}
          {buttons.length > 0 && (
            <>
              <div className="hd-s">Buttons</div>
              <table className="hd-keys">
                <tbody>
                  {buttons.map((b) => (
                    <tr key={b.label}>
                      <td className="hd-k">{b.label}</td>
                      <td>{b.title ? b.title.replace(/\s*\([^)]*\)\s*$/, "") : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {/* 3. its keys: the key behind each button, then the keys every panel has (read live, so a rebinding shows here) */}
          <div className="hd-s">Keys</div>
          <table className="hd-keys">
            <tbody>
              {buttons.map((b) => (
                <tr key={b.label}>
                  <td className="hd-k">{b.shift ? "Shift+" : ""}{b.key}</td>
                  <td>{b.label}</td>
                </tr>
              ))}
              {GLOBAL_KEYS.map(([action, text]) => (
                <tr key={action}>
                  <td className="hd-k">{keys[action][0] ?? "UNBOUND"}</td>
                  <td>{text}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* The typed form is only a learning aid, so it comes last and small. */}
          <div className="dim">
            Typed: {def.needsSecurity ? "<SECURITY> " : ""}
            {def.code} {def.argsSchema ?? ""}
            {def.needsSecurity ? " (a security is a ticker such as AAPL)" : ""}
          </div>
          {related.length > 0 && (
            <>
              <div className="hd-s">Related functions</div>
              <div className="hd-rel">
                {related.map((it) => (
                  <button
                    key={it.fn}
                    type="button"
                    className="pt-b"
                    title={it.label}
                    onClick={() => {
                      // Close without handing focus back to the old element, run it in this panel, land on the command line.
                      helpDrawer.set(() => null);
                      runItem(panel.id, it);
                      focusCommandLine();
                    }}
                  >
                    {it.fn}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </aside>
  );
}
