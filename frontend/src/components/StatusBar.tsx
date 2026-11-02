import { useEffect } from "react";
import { DISCLAIMER } from "../config";
import { effectiveBindings, type Action } from "../keys/keys";
import { settingsStore } from "../settings/runtime";
import { kite, refreshKite } from "../net/kite";
import { useRunningJobs } from "../net/jobs";
import { link } from "../net/socket";
import { sources } from "../net/sources";
import { useStore } from "../state/store";
import { ModeToggle } from "../gui/ModeToggle";
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

/** Phase 15: Kite login state, asked once at start (and after KITE login/logout). Nothing is shown without a key or when unknown. */
function KiteState() {
  const k = useStore(kite, (s) => s);
  useEffect(() => {
    void refreshKite();
  }, []);
  if (!k || k.state === "NO KEY") return null;
  return (
    <span>
      KITE <span className={k.state === "OK" ? "up" : k.state === "LOGGED OUT" ? "warn" : "err"}>{k.state.replace(/^KITE /, "")}</span>
    </span>
  );
}

/** One-line key hints for bound actions only: the chords come from the bindings in force (defaults + SETTINGS overrides). */
const HINTS: [Action, string][] = [
  ["focusCommand", "COMMAND"],
  ["nextPanel", "NEXT PANEL"],
  ["focusPanel", "PANEL"],
  ["splitVertical", "SPLIT"],
  ["closePanel", "CLOSE"],
  ["maximize", "MAX"],
  ["refresh", "REFRESH"],
  ["windowMenu", "MENU"],
  ["exportCsv", "CSV"],
  ["saveWorkspace", "SAVE"],
  ["cheatsheet", "ALL KEYS"],
];

function KeyHints() {
  useStore(settingsStore, (s) => s.keys); // re-read when SETTINGS rebinds a key
  const b = effectiveBindings();
  return (
    <div className="keys" aria-hidden="true">
      {HINTS.map(([action, label]) => {
        const list = b[action] ?? [];
        const chord = list.find((c) => !c.startsWith("Ctrl+")) ?? list[0];
        return chord ? (
          <span key={action}>
            <b>{chord.toUpperCase()}</b>
            {label}
          </span>
        ) : null;
      })}
    </div>
  );
}

export function StatusBar() {
  const l = useStore(link, (s) => s);
  const focus = useStore(workspace, (s) => s.focus);
  const count = useStore(workspace, (s) => Object.keys(s.panels).length);
  const max = useStore(workspace, (s) => s.maximized);
  const layout = useStore(workspace, (s) => s.name);
  const cls = l.status === "OK" ? "up" : l.status === "DOWN" ? "err" : "warn";
  return (
    <>
    <KeyHints />
    <footer className="status">
      <span>
        <span className={"dot " + cls} />BACKEND <span className={cls}>{l.status}</span>
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
      <KiteState />
      <AlertFlash />
      <span className="sp" />
      <ModeToggle />
      <span>{DISCLAIMER}</span>
    </footer>
    </>
  );
}
