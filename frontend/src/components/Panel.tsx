import { Component, Profiler, Suspense, lazy, useEffect, type ComponentType, type ReactNode } from "react";
import { FUNCTIONS, type FunctionProps } from "../functions/registry";
import { panelPainted, recordPanelRender } from "../perf/metrics";
import { useStore } from "../state/store";
import { currentView, focusPanel, workspace } from "../state/workspace";

const lazyCache = new Map<string, ComponentType<FunctionProps>>();
function moduleFor(code: string): ComponentType<FunctionProps> | null {
  const def = FUNCTIONS.get(code);
  if (!def?.load) return null;
  let c = lazyCache.get(code);
  if (!c) lazyCache.set(code, (c = lazy(def.load)));
  return c;
}

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

export function Panel({ id }: { id: number }) {
  const panel = useStore(workspace, (s) => s.panels[id]);
  const focused = useStore(workspace, (s) => s.focus === id);
  const view = currentView(panel);
  const Mod = view.fn ? moduleFor(view.fn) : null;
  const title = [view.security?.symbol, view.fn].filter(Boolean).join(" | ") || "—";
  const viewKey = `${panel.pos}:${view.fn}:${view.security?.symbol}:${view.args.join(" ")}`;

  return (
    <section className={"panel" + (focused ? " focus" : "")} data-panel={id} onMouseDown={() => focusPanel(id)}>
      <header className="ph">
        <span className="id">{id}</span>
        <span>{title}</span>
        {panel.views.length > 1 && <span className="dim">{panel.pos + 1}/{panel.views.length}</span>}
      </header>
      <div className="pb">
        <PanelBoundary resetKey={viewKey}>
          <Profiler id={String(id)} onRender={(_id, _phase, ms) => recordPanelRender(id, ms)}>
            <Suspense fallback={<div className="dim">LOADING {view.fn}…</div>}>
              <Painted key={viewKey} panelId={id}>
                {!view.fn ? <Empty /> : Mod ? <Mod panelId={id} security={view.security} args={view.args} /> : <NotBuilt code={view.fn} />}
              </Painted>
            </Suspense>
          </Profiler>
        </PanelBoundary>
      </div>
    </section>
  );
}
