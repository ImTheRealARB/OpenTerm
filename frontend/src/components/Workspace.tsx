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
  return (
    <main className="ws">
      {maximized ? <Panel id={maximized} /> : <Node node={layout} />}
      {overlay}
    </main>
  );
}
