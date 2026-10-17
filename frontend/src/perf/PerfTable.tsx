import { useEffect, useState } from "react";
import { snapshot, watchFrames } from "./metrics";

const f = (v: number, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : "—");

/** Budgets from the spec; a value over budget renders red. */
const BUDGET = { keyEcho: 16.7, cmdToPaint: 100, tickToPixel: 50, frameP95: 20, heapMB: 500 };

function Row({ k, v, budget }: { k: string; v: number; budget?: number }) {
  const over = budget !== undefined && Number.isFinite(v) && v > budget;
  return (
    <tr>
      <td>{k}</td>
      <td className={"n " + (over ? "err" : "")}>{f(v)}</td>
      <td className="n dim">{budget ?? ""}</td>
    </tr>
  );
}

export function PerfTable({ detailed = false }: { detailed?: boolean }) {
  const [s, setS] = useState(snapshot);
  useEffect(() => {
    const stop = watchFrames();
    const id = setInterval(() => setS(snapshot()), 500);
    return () => {
      stop();
      clearInterval(id);
    };
  }, []);

  const gauges = Object.entries(s.gauges);
  return (
    <table className="t">
      <colgroup>
        <col />
        <col style={{ width: 70 }} />
        <col style={{ width: 50 }} />
      </colgroup>
      <thead>
        <tr>
          <th>METRIC</th>
          <th className="n">NOW</th>
          <th className="n">BUDGET</th>
        </tr>
      </thead>
      <tbody>
        <Row k="FPS" v={s.fps} />
        <Row k="FRAME P95 MS" v={s.frameP95} budget={BUDGET.frameP95} />
        <Row k="LONG TASKS" v={s.longTasks} />
        <Row k="KEY ECHO P95 MS" v={s.keyEcho.p95} budget={BUDGET.keyEcho} />
        <Row k="CMD→PAINT P95 MS" v={s.cmdToPaint.p95} budget={BUDGET.cmdToPaint} />
        <Row k="TICK→PIXEL P95 MS" v={s.tickToPixel.p95} budget={BUDGET.tickToPixel} />
        <Row k="WS RTT MS" v={s.wsRtt.last} />
        <Row k="WS MSGS/S" v={s.gauges["ws.msgsPerSec"] ?? NaN} />
        <Row k="CACHE HIT %" v={s.gauges["cache.hitPct"] ?? NaN} />
        <Row k="JS HEAP MB" v={s.heapMB} budget={BUDGET.heapMB} />
        {detailed &&
          gauges
            .filter(([k]) => k.startsWith("provider."))
            .map(([k, v]) => <Row key={k} k={k.toUpperCase() + " MS"} v={v} />)}
        {detailed &&
          Object.entries(s.panels).map(([id, v]) => <Row key={id} k={`PANEL ${id} RENDER P95 MS`} v={v} />)}
      </tbody>
    </table>
  );
}
