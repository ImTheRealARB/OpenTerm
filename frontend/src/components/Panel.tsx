import { Component, Profiler, useEffect, useReducer, type ReactNode } from "react";
import { FUNCTIONS, loadModule, loadedModule } from "../functions/registry";
import { panelPainted, recordPanelRender } from "../perf/metrics";
import { PanelToolbar } from "../gui/PanelToolbar";
import { settingsStore } from "../settings/runtime";
import { PanelIdContext } from "../state/panelContext";
import { useStore } from "../state/store";
import { currentView, focusPanel, workspace } from "../state/workspace";
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

function NotBuilt({ code }: { code: string }) {
  const def = FUNCTIONS.get(code)!;
  return (
    <div>
      <span className="warn">{code}</span> {def.title.toUpperCase()}: <span className="warn">NOT BUILT YET (PHASE {def.phase})</span>
    </div>
  );
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
    if (def?.load && !Mod) loadModule(code).then(rerender, (e: Error) => setError(`CANNOT LOAD ${code}: ${e.message}`));
  }, [code, def, Mod]);

  if (!def?.load) return <NotBuilt code={code} />;
  if (error) return <div className="err">{error}</div>;
  if (!Mod) return <div className="dim">LOADING {code}…</div>;
  return (
    <PanelIdContext.Provider value={panelId}>
      <Mod panelId={panelId} security={view.security} args={view.args} />
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
  // The sticky security stays on the panel, but the tab only names it when this function uses it
  // (bare `N` shows that security's news).
  const usesSecurity = (view.fn && FUNCTIONS.get(view.fn)?.needsSecurity) || (view.fn === "N" && view.args.length === 0);
  const tickerPart = usesSecurity ? view.security?.symbol : undefined;
  const fnPart = view.fn;
  // New command = new history entry = remount. In-place edits (timeframe, list) keep the instance.
  const mountKey = `${panel.pos}:${view.fn}:${view.security?.symbol}`;
  const resetKey = `${mountKey}:${view.args.join(" ")}`;

  return (
    <section className={"panel" + (focused ? " focus" : "")} data-panel={id} onMouseDown={() => focusPanel(id)}>
      <header className="ph">
        <span className="id">{id}</span>
        <span>
          {tickerPart && <span className="tk">{tickerPart}</span>}
          {tickerPart && fnPart && " | "}
          {fnPart && <span className="fnm">{fnPart}</span>}
          {!tickerPart && !fnPart && "—"}
        </span>
        {panel.views.length > 1 && <span className="dim">{panel.pos + 1}/{panel.views.length}</span>}
        <span className="wm-sp" />
        {MENUS.map((m, i) => (
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
        ))}
      </header>
      {menu && <WindowMenu id={id} />}
      {gui && <PanelToolbar id={id} fn={view.fn} args={view.args} />}
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
