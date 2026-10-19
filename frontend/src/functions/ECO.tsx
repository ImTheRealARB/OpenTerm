/** Economic calendar: US data releases from the BLS and BEA official schedules, Eastern times. */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { macroApi, type EcoEvent, type EcoPayload } from "../net/api";
import { replaceView } from "../state/workspace";
import { ECO_WINDOWS, addDays, dayLabel, nyToday, parseEcoArgs } from "./macroArgs";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { useEnvelope } from "./secPanel";
import { useCsvExport } from "./tableExport";

const POLL_MS = 300_000;

interface Row extends EcoEvent {
  /** First event of its day shows the date; the rest leave it blank. */
  showDate: boolean;
}

const COLUMNS: Column<Row>[] = [
  { title: "DATE", width: 16, text: (r) => (r.showDate ? dayLabel(r.date) : ""), color: () => "dim" },
  { title: "TIME ET", width: 7, text: (r) => r.time ?? "-", color: () => "dim" },
  { title: "IMPACT", width: 6, text: (r) => (r.major ? "MAJOR" : ""), color: () => "acc" },
  { title: "RELEASE", width: 66, text: (r) => r.name, color: (r) => (r.ts * 1000 < Date.now() ? "dim" : "fg") },
  { title: "SOURCE", width: 6, text: (r) => r.agency, color: () => "dim" },
];

function toRows(events: EcoEvent[]): Row[] {
  return events.map((e, i) => ({ ...e, showDate: i === 0 || events[i - 1].date !== e.date }));
}

export default function ECO({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseEcoArgs(args), [args]);
  const grid = useRef<GridHandle>(null);
  const pRef = useRef(p);
  pRef.current = p;

  const { env, error, loading, reload: load } = useEnvelope<EcoPayload>(`${p.start}|${p.days}`, (fresh) => macroApi.eco(p.start, p.days, fresh));

  useEffect(() => {
    const t = setInterval(() => void load(false), POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const rows = useMemo(() => toRows((env?.data.events ?? []).filter((e) => !p.major || e.major)), [env, p.major]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => ({ name: "ECO", header: COLUMNS.map((c) => c.title), rows: rows.map((r) => [r.date, r.time ?? "", r.major ? "MAJOR" : "", r.name, r.agency]) }));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        const set = (next: Partial<{ days: number; major: boolean; start: string | null }>) => {
          const q = { ...pRef.current, ...next };
          replaceView(panelId, (v) => ({ ...v, args: [String(q.days), ...(q.major ? ["MAJOR"] : []), ...(q.start ? [q.start] : [])] }));
        };
        const n = Number(e.key);
        if (n >= 1 && n <= ECO_WINDOWS.length) {
          set({ days: ECO_WINDOWS[n - 1] });
          return true;
        }
        switch (e.key) {
          case "ArrowLeft":
          case "ArrowRight": {
            const q = pRef.current;
            set({ start: addDays(q.start ?? nyToday(), (e.key === "ArrowLeft" ? -1 : 1) * q.days) });
            return true;
          }
          case "t":
            set({ start: null });
            return true;
          case "m":
            set({ major: !pRef.current.major });
            return true;
          case "F5":
            void load(true);
            return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const d = env?.data;
  const hi = d ? addDays(d.start, d.days - 1) : null;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">ECONOMIC CALENDAR</span>
        {d && ` · ${d.start} TO ${hi} (${d.days}D)`}
        {p.major && <span className="acc"> · MAJOR ONLY</span>}
        {d && ` · ${rows.length} RELEASES`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · J/K MOVE · 1-4 WINDOW (7/14/30/62D) · ←/→ SHIFT · T TODAY · M MAJOR · E CSV · F5</span>
      </div>
      <div className="dim">
        US RELEASES FROM THE BLS AND BEA OFFICIAL SCHEDULES (JOBS, CPI, PPI, JOLTS, GDP, PCE, TRADE), US EASTERN. FOMC, CENSUS AND PRIVATE SURVEYS ARE NOT IN THIS SOURCE. NO FORECASTS OR ACTUALS.
      </div>
      {p.error && <div className="err">{p.error}</div>}
      {d?.notes?.map((n) => <div key={n} className="warn">{n}</div>)}
      {d && d.failed.length > 0 && <div className="warn">{d.failed.join(" + ")} FEED DID NOT ANSWER: ITS RELEASES ARE MISSING BELOW. F5 RETRIES.</div>}
      {d && d.coverage_end && hi && hi > d.coverage_end && <div className="warn">SOURCE SCHEDULES END {d.coverage_end}.</div>}
      {d && rows.length === 0 && !error && (
        <div className="dim">NO {p.major ? "MAJOR " : ""}RELEASES IN THIS WINDOW{p.major ? " (M SHOWS ALL)" : ""}. ←/→ SHIFTS THE WINDOW.</div>
      )}
      <ErrorLine error={error} hasData={!!env} usage="ECO [1-62] [MAJOR] [YYYY-MM-DD]" />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
