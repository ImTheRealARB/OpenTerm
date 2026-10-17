import { DISCLAIMER } from "../config";
import { useRunningJobs } from "../net/jobs";
import { link } from "../net/socket";
import { sources } from "../net/sources";
import { useStore } from "../state/store";
import { AlertFlash } from "./AlertFlash"; // Phase 8
import { workspace } from "../state/workspace";

const PCLS: Record<string, string> = { OK: "up", DEGRADED: "warn", DOWN: "err", IDLE: "dim" };

function Providers() {
  const s = useStore(sources, (v) => v);
  if (!s) return <span>PROVIDERS <span className="err">UNKNOWN</span></span>;
  return (
    <span>
      {s.fixtures && <span className="warn">FIXTURES </span>}
      {s.providers.map((p) => (
        <span key={p.name}>
          {p.name.toUpperCase()} <span className={PCLS[p.status]}>{p.status}</span>
          {p.latency_p50_ms != null && ` ${p.latency_p50_ms.toFixed(0)}MS`}{" "}
        </span>
      ))}
    </span>
  );
}

/** Phase 11: shown only while a background job is queued or running. */
function JobsCount() {
  const n = useRunningJobs();
  return n > 0 ? (
    <span>
      JOBS <span className="acc">{n}</span>
    </span>
  ) : null;
}

export function StatusBar() {
  const l = useStore(link, (s) => s);
  const focus = useStore(workspace, (s) => s.focus);
  const count = useStore(workspace, (s) => Object.keys(s.panels).length);
  const max = useStore(workspace, (s) => s.maximized);
  const layout = useStore(workspace, (s) => s.name);
  const cls = l.status === "OK" ? "up" : l.status === "DOWN" ? "err" : "warn";
  return (
    <footer className="status">
      <span>
        BACKEND <span className={cls}>{l.status}</span>
        {l.status === "OK" && <> {l.rttMs.toFixed(0)}MS</>}
      </span>
      <Providers />
      <span>
        PANEL {focus}/{count}
        {max ? " MAX" : ""}
      </span>
      <span>
        LAYOUT <span className={layout ? "acc" : "dim"}>{layout ?? "NONE"}</span>
      </span>
      <span>MODE CMD</span>
      <JobsCount />
      <AlertFlash />
      <span className="sp" />
      <span>{DISCLAIMER}</span>
    </footer>
  );
}
