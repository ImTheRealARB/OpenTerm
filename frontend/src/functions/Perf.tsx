import { Suspense, lazy, useEffect, useState } from "react";
import { commandLog } from "../perf/metrics";
import { PerfTable } from "../perf/PerfTable";
import type { FunctionProps } from "./registry";

// Separate chunk: only load-test sessions pay for the chart library and generated data.
const TestGrid = lazy(() => import("./PerfViews").then((m) => ({ default: m.TestGrid })));
const TestChart = lazy(() => import("./PerfViews").then((m) => ({ default: m.TestChart })));
const CalcBench = lazy(() => import("./PerfViews").then((m) => ({ default: m.CalcBench })));

export default function Perf({ panelId, args }: FunctionProps) {
  const mode = args[0]?.toUpperCase();
  const n = Math.min(1_000_000, Math.max(1, Number(args[1]) || (mode === "CHART" ? 50_000 : 10_000)));
  if (mode === "CALC")
    return (
      <Suspense fallback={<div className="dim">LOADING TEST VIEW…</div>}>
        <CalcBench />
      </Suspense>
    );
  if (mode === "GRID" || mode === "CHART")
    return (
      <Suspense fallback={<div className="dim">LOADING TEST VIEW…</div>}>
        {mode === "GRID" ? <TestGrid panelId={panelId} rows={n} /> : <TestChart panelId={panelId} bars={n} />}
      </Suspense>
    );
  return <PerfMonitor />;
}

function PerfMonitor() {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const recent = commandLog.slice(-15).reverse();
  return (
    <div>
      <h2>PERF</h2>
      <PerfTable detailed />
      <div className="dim">LOAD TESTS: PERF GRID [ROWS] · PERF CHART [BARS] · PERF CALC</div>
      <h2>RECENT COMMANDS (SUBMIT → PAINT)</h2>
      <table className="t">
        <tbody>
          {recent.map((c) => (
            <tr key={c.at + c.cmd}>
              <td>{c.cmd.toUpperCase()}</td>
              <td className={"n " + (c.ms > 100 ? "err" : "")} style={{ width: 80 }}>
                {c.ms.toFixed(1)} MS
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
