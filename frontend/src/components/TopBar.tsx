import { useEffect, useRef } from "react";
import { statusMsg } from "../command/execute";
import { APP_NAME } from "../config";
import { MARKETS, isOpen } from "../markets/hours";
import { useStore } from "../state/store";
import { CommandLine } from "./CommandLine";

const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const utcFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" });

/** Clock updates its own DOM once a second; it never re-renders React. */
function Clock() {
  const local = useRef<HTMLSpanElement>(null);
  const utc = useRef<HTMLSpanElement>(null);
  const lights = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      local.current!.textContent = timeFmt.format(now);
      utc.current!.textContent = utcFmt.format(now) + "Z";
      MARKETS.forEach((m, i) => {
        const el = lights.current[i];
        if (el) el.className = isOpen(m, now) ? "mk open" : "mk";
      });
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="clock">
      {MARKETS.map((m, i) => (
        <span key={m.code} ref={(el) => void (lights.current[i] = el)} className="mk" title={`${m.code} ${m.tz} (holidays not modelled)`}>
          {m.code}
        </span>
      ))}
      <span ref={local} />
      <span ref={utc} className="dim" />
    </div>
  );
}

function Message() {
  const msg = useStore(statusMsg, (s) => s);
  return <div className={"msg " + (msg?.kind ?? "")}>{msg?.text}</div>;
}

export function TopBar() {
  return (
    <div className="top">
      <div className="brand">{APP_NAME}</div>
      <CommandLine />
      <Message />
      <Clock />
    </div>
  );
}
