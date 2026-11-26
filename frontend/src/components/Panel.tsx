import { Component, Profiler, useEffect, useReducer, type ReactNode } from "react";
import { execute } from "../command/execute";
import { FUNCTIONS, loadModule, loadedModule, showsSecurity } from "../functions/registry";
import { panelPainted, recordPanelRender } from "../perf/metrics";
import { openHelp } from "../gui/helpState";
import { LazyPanelToolbar } from "../gui/LazyPanelToolbar";
import { LazyQuoteStrip } from "../gui/LazyQuoteStrip";
import { shortTitle } from "../gui/titleText";
import { settingsStore } from "../settings/runtime";
import { PanelIdContext } from "../state/panelContext";
import { useStore } from "../state/store";
import { currentView, focusPanel, setLink, workspace } from "../state/workspace";
import { nextGroup } from "../state/linkGroups";
import { MENUS, type MenuIndex } from "./windowMenu";
import { closeWindowMenu, itemsOf, openWindowMenu, runItem, windowMenu } from "./windowMenuRun";

/** One panel crashing never takes down the app. */
class PanelBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) return <div className="err">PANEL ERROR: {this.state.error.message}. RUN ANOTHER COMMAND TO RECOVER.</div>;
    return this.props.children;
  }
}

/** Reports to the perf layer once this view's content has rendered. */
function Painted({ panelId, children }: { panelId: number; children: ReactNode }) {
  useEffect(() => panelPainted(panelId));
  return <>{children}</>;
}

function Empty() {
  return <div className="dim">EMPTY PANEL. TYPE A COMMAND, E.G. AAPL GP</div>;
}

/**
 * Renders a function module without React.lazy/Suspense: React 19 holds back revealed Suspense
 * content for ~300 ms, which cost every first use of a function 300 ms (measured). Loaded modules
 * render synchronously; a missing one shows a plain LOADING line until its chunk arrives.
 */
function FunctionView({ panelId, view }: { panelId: number; view: ReturnType<typeof currentView> }) {
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const code = view.fn!;
  const def = FUNCTIONS.get(code);
  const Mod = loadedModule(code);
  const [error, setError] = useReducer((_: string | null, e: string | null) => e, null);

  useEffect(() => {
    if (def && !Mod) loadModule(code).then(rerender, (e: Error) => setError(`CANNOT LOAD ${code}: ${e.message}`));
  }, [code, def, Mod]);

  // Not reachable from a command or a saved layout (both drop unknown codes first); a plain error beats a crash if it ever happens.
  if (!def) return <div className="err">UNKNOWN FUNCTION: {code}</div>;
  if (error) return <div className="err">{error}</div>;
  if (!Mod) return <div className="dim">LOADING {code}…</div>;
  return (
    <PanelIdContext.Provider value={panelId}>
      <Mod panelId={panelId} security={view.security} args={view.args} source={view.source} />
    </PanelIdContext.Provider>
  );
}

/** Drop-down under the title bar: numbered items, the cursor row highlighted. */
function WindowMenu({ id }: { id: number }) {
  const state = useStore(windowMenu, (s) => s);
  useStore(workspace, (s) => s.panels[id]);
  if (!state || state.panel !== id) return null;
  const items = itemsOf(state);
  return (
    <div className="wm" data-testid="window-menu" onMouseDown={(e) => e.stopPropagation()}>
      {items.length === 0 && <div className="dim">NOTHING HERE</div>}
      {items.map((it, i) => (
        <div key={i} className={i === state.sel ? "on" : undefined} onMouseDown={() => runItem(id, it)}>
          <span className="wm-n">{i < 9 ? `${i + 1})` : ""}</span> {it.label}
          {it.kind === "history" && it.current && <span className="dim"> (CURRENT)</span>}
        </div>
      ))}
      <div className="wm-hint">1-9 PICK · ↑↓ ENTER · ←→ MENU · ESC CLOSE</div>
    </div>
  );
}

export function Panel({ id }: { id: number }) {
  const panel = useStore(workspace, (s) => s.panels[id]);
  const menu = useStore(windowMenu, (s) => (s?.panel === id ? s : null));
  const focused = useStore(workspace, (s) => s.focus === id);
  // GUI mode adds a button row under the title bar. Terminal mode renders nothing extra.
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const view = currentView(panel);
  // The sticky security stays on the panel, but the tab only names it when this function uses it (see `showsSecurity`).
  const tickerPart = showsSecurity(view) ? view.security?.symbol : undefined;
  const fnPart = view.fn;
  // GUI only: the function's plain title ("Price chart") follows the code, so a beginner sees what the panel is.
  const plainTitle = gui && view.fn ? shortTitle(FUNCTIONS.get(view.fn)?.title ?? "") : "";
  // GUI only: a one-line quote strip under the button row. Functions that already lead with the live price (DES, QR) skip it.
  const showStrip = gui && !!tickerPart && !(view.fn && FUNCTIONS.get(view.fn)?.leadsWithPrice);
  // New command = new history entry = remount. In-place edits (timeframe, list) keep the instance.
  const mountKey = `${panel.pos}:${view.fn}:${view.security?.symbol}`;
  const resetKey = `${mountKey}:${view.args.join(" ")}:${view.source ?? ""}`;

  return (
    <section className={"panel" + (focused ? " focus" : "")} data-panel={id} onMouseDown={() => focusPanel(id)}>
      <header className="ph">
        <span className="id">{id}</span>
        {/* Phase 22 link group chip: the group's letter in its colour; a click moves the panel to the next group (LINK A|B|C|D|OFF by keyboard). */}
        <button
          type="button"
          tabIndex={-1}
          className={"ph-link" + (panel.link ? ` link-${panel.link}` : "")}
          data-testid="panel-link"
          title={panel.link ? `Link group ${panel.link}: panels in this group follow each other's security. Click for the next group.` : "Not linked. Click to put this panel in link group A."}
          onClick={(e) => {
            e.stopPropagation();
            setLink(id, nextGroup(panel.link));
          }}
        >
          {panel.link ?? "·"}
        </button>
        <span>
          {tickerPart && <span className="tk">{tickerPart}</span>}
          {tickerPart && fnPart && " | "}
          {fnPart && <span className="fnm">{fnPart}</span>}
          {!tickerPart && !fnPart && "—"}
          {view.source && <span className="dim"> SRC={view.source.toUpperCase()}</span>}
        </span>
        {plainTitle && <span className="ph-plain">{"· " + plainTitle}</span>}
        {panel.views.length > 1 && <span className="dim ph-pos">{panel.pos + 1}/{panel.views.length}</span>}
        <span className="wm-sp" />
        {/* GUI only: the same RELATED menu as the "RELATED ▾" item below, but as a plain-words button a beginner can find.
            It opens/closes menu 1 through the shared window-menu state, so there is one menu and one set of keys (1-9, arrows, Enter, Esc). */}
        {gui && (
          <button
            type="button"
            className={"ph-rel" + (menu?.menu === 1 ? " on" : "")}
            data-testid="related-btn"
            aria-haspopup="menu"
            aria-expanded={menu?.menu === 1}
            onMouseDown={(e) => {
              e.stopPropagation(); // same pattern as the menu titles: the panel's own mousedown must not close what this opens
              if (menu?.menu === 1) closeWindowMenu();
              else openWindowMenu(id, 1);
            }}
          >
            Related functions
          </button>
        )}
        {MENUS.map((m, i) => (gui && m === "RECENT" ? null : (
          <span
            key={m}
            className={"wm-t" + (menu?.menu === i ? " on" : "")}
            onMouseDown={(e) => {
              e.stopPropagation();
              if (menu?.menu === i) closeWindowMenu();
              else openWindowMenu(id, i as MenuIndex);
            }}
          >
            {m} ▾
          </span>
        )))}
        {/* Help for this panel's function. GUI: the help drawer scoped to this panel. Terminal: the HELP <FN> command, which
            shows the same help as a panel. Keyboard route is that command (the "?" key is already the shortcut sheet). */}
        <button
          type="button"
          className="ph-help"
          data-testid="panel-help"
          aria-label={fnPart ? `Help for ${fnPart}` : "Help"}
          title={fnPart ? `Help for ${fnPart}` : "Help"}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            focusPanel(id);
            if (gui) openHelp(id, e.currentTarget);
            else execute(fnPart ? `HELP ${fnPart}` : "HELP");
          }}
        >
          ?
        </button>
      </header>
      {menu && <WindowMenu id={id} />}
      {gui && <LazyPanelToolbar id={id} fn={view.fn} args={view.args} symbol={view.security?.symbol} />}
      {showStrip && <LazyQuoteStrip key={tickerPart} symbol={tickerPart!} />}
      <div className="pb">
        <PanelBoundary resetKey={resetKey}>
          <Profiler id={String(id)} onRender={(_id, _phase, ms) => recordPanelRender(id, ms)}>
            <Painted key={mountKey} panelId={id}>
              {view.fn ? <FunctionView panelId={id} view={view} /> : <Empty />}
            </Painted>
          </Profiler>
        </PanelBoundary>
      </div>
    </section>
  );
}
