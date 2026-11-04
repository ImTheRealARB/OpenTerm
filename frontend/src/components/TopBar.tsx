import { useEffect, useRef } from "react";
import { statusMsg } from "../command/execute";
import { APP_NAME } from "../config";
import { MARKETS, basisNote, basisOf, lightOf } from "../markets/hours";
import { loadHolidays, unavailable } from "../markets/holidays";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { CommandLine } from "./CommandLine";

/** Phase 10: zones come from SETTINGS (default LOCAL + UTC). The first clock shows seconds. */
function zoneFormat(zone: string, seconds: boolean): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}), hourCycle: "h23",
    ...(zone === "LOCAL" ? {} : { timeZone: zone }),
  });
}

const zoneLabel = (zone: string) =>
  zone === "LOCAL" || zone === "UTC" ? "" : (zone.split("/").pop() ?? zone).replace(/_/g, " ").toUpperCase().slice(0, 10) + " ";

/** Clock updates its own DOM once a second; it never re-renders React (except when the zones change). */
function Clock() {
  const zones = useStore(settingsStore, (st) => st.clocks);
  const clocks = useRef<(HTMLSpanElement | null)[]>([]);
  const lights = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    const fmts = zones.map((z, i) => {
      try {
        return zoneFormat(z, i === 0);
      } catch {
        return zoneFormat("UTC", i === 0); // a zone this browser does not know
      }
    });
    const tick = () => {
      const now = new Date();
      zones.forEach((z, i) => {
        const el = clocks.current[i];
        if (el) el.textContent = zoneLabel(z) + fmts[i].format(now) + (z === "UTC" ? "Z" : "");
      });
      MARKETS.forEach((m, i) => {
        const el = lights.current[i];
        if (!el) return;
        const light = lightOf(m, now);
        el.className = light === "closed" ? "mk" : `mk ${light}`;
        el.textContent = light === "hol" ? `${m.code} HOL` : light === "early" ? `${m.code} EARLY` : m.code;
        const basis = basisOf(m, now);
        el.title = `${m.code} ${m.tz} · ` + (basis ? basisNote(basis) : unavailable.has(m.code) ? "NO HOLIDAY DATA: WEEKDAY SESSIONS ONLY" : "HOLIDAYS LOADING");
      });
    };
    tick();
    void loadHolidays();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [zones]);

  return (
    <div className="clock">
      {MARKETS.map((m, i) => (
        <span key={m.code} ref={(el) => void (lights.current[i] = el)} className="mk" title={`${m.code} ${m.tz}`}>
          {m.code}
        </span>
      ))}
      {zones.map((z, i) => (
        <span key={z + i} ref={(el) => void (clocks.current[i] = el)} className={i === 0 ? undefined : "dim"} title={z} />
      ))}
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
