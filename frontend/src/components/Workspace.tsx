import { TabStrip } from "../gui/TabStrip";
import { useTabsOn } from "../gui/tabsState";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { workspace, type Layout } from "../state/workspace";
import { Panel } from "./Panel";

function Node({ node }: { node: Layout }) {
  if (node.t === "leaf") return <Panel key={node.id} id={node.id} />;
  const pct = (node.ratio * 100).toFixed(2);
  return (
    <div className={"split " + node.dir}>
      <div className={"split " + node.dir} style={{ flex: `0 0 ${pct}%` }}>
        <Node node={node.a} />
      </div>
      <div className={"split " + node.dir} style={{ flex: "1 1 0" }}>
        <Node node={node.b} />
      </div>
    </div>
  );
}

export function Workspace({ overlay }: { overlay?: React.ReactNode }) {
  const layout = useStore(workspace, (s) => s.layout);
  const maximized = useStore(workspace, (s) => s.maximized);
  const focus = useStore(workspace, (s) => s.focus);
  // Tabs are a GUI-mode layout: a strip of tabs plus the focused panel at full size. Terminal mode is always tiled.
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const tabsPref = useTabsOn();
  const tabs = gui && tabsPref; // two separate hook calls: `a && useX()` would skip a hook on some renders, which React forbids
  return (
    <main className="ws">
      {tabs ? (
        <div className="ws-tabs">
          <TabStrip />
          {/* key={focus}: each tab gets its own clean mount, even when two tabs show the same function and symbol */}
          <Panel key={focus} id={focus} />
        </div>
      ) : maximized ? (
        <Panel id={maximized} />
      ) : (
        <Node node={layout} />
      )}
      {overlay}
    </main>
  );
}
