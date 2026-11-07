import { useEffect, useRef, useState } from "react";
import { systemApi } from "../net/systemApi";
import type { LogRecord } from "../net/types";

const MAX = 500;
const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const lvl = (l: string) => (l === "ERROR" || l === "CRITICAL" ? "err" : l === "WARNING" ? "warn" : "dim");

export default function Log() {
  const [rows, setRows] = useState<LogRecord[]>([]);
  const [down, setDown] = useState(false);
  const last = useRef(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { records } = await systemApi.log(last.current);
        if (!alive) return;
        setDown(false);
        if (records.length) {
          last.current = records[records.length - 1].seq;
          setRows((r) => [...r, ...records].slice(-MAX));
        }
      } catch {
        if (alive) setDown(true);
      }
    };
    void tick();
    const id = setInterval(tick, 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    const el = box.current?.parentElement;
    if (el) el.scrollTop = el.scrollHeight;
  }, [rows]);

  return (
    <div ref={box}>
      <h2>LOG {down && <span className="err">BACKEND DOWN</span>}</h2>
      {rows.length === 0 && <div className="dim">NO LOG RECORDS YET</div>}
      {rows.map((r) => (
        <div key={r.seq}>
          <span className="dim">{time.format(r.t * 1000)} </span>
          <span className={lvl(r.level)}>{r.level.padEnd(7)} </span>
          <span className="dim">{r.logger.replace("openterm.", "").padEnd(10)} </span>
          {r.msg}
        </div>
      ))}
    </div>
  );
}
