import { useEffect, useState } from "react";
import { commandLog } from "../perf/metrics";
import { PerfTable } from "../perf/PerfTable";

export default function Perf() {
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
