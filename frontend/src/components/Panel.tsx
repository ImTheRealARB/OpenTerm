import { Component, Profiler, useEffect, useReducer, type ReactNode } from "react";
import { FUNCTIONS, loadModule, loadedModule } from "../functions/registry";
import { panelPainted, recordPanelRender } from "../perf/metrics";
import { useStore } from "../state/store";
import { currentView, focusPanel, workspace } from "../state/workspace";

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
  return <Mod panelId={panelId} security={view.security} args={view.args} />;
}

export function Panel({ id }: { id: number }) {
  const panel = useStore(workspace, (s) => s.panels[id]);
  const focused = useStore(workspace, (s) => s.focus === id);
  const view = currentView(panel);
  const title = [view.security?.symbol, view.fn].filter(Boolean).join(" | ") || "—";
  // New command = new history entry = remount. In-place edits (timeframe, list) keep the instance.
  const mountKey = `${panel.pos}:${view.fn}:${view.security?.symbol}`;
  const resetKey = `${mountKey}:${view.args.join(" ")}`;

  return (
    <section className={"panel" + (focused ? " focus" : "")} data-panel={id} onMouseDown={() => focusPanel(id)}>
      <header className="ph">
        <span className="id">{id}</span>
        <span>{title}</span>
        {panel.views.length > 1 && <span className="dim">{panel.pos + 1}/{panel.views.length}</span>}
      </header>
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
