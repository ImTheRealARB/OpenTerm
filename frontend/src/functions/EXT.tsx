/**
 * EXT: third-party extensions. One generic panel, so an extension needs no frontend build.
 *   EXT / EXT LIST          the installed extensions: who wrote them, what they add, ON / OFF / ERR
 *   EXT ENABLE|DISABLE name the switch (everything is OFF until the user turns it on)
 *   EXT name [route] [args] an enabled extension's table (Grid) or series (chart)
 * Extensions are other people's code and run with the user's permissions; the list and every extension panel say so.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ChartView, type ChartHandle } from "../chart/ChartView";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError } from "../net/core";
import { extApi, type ExtList } from "../net/extApi";
import { gridColumns, type TableRow } from "../research/tablePayload";
import { navigate, replaceView } from "../state/workspace";
import { useLatest } from "../state/useLatest";
import { EXT_USAGE, parseExtArgs, pickRoute, provenance, seriesBars, statusClass, tableSection, type ExtInfo, type ExtPayload } from "./extPayload";
import { usePanelRefresh } from "./panelRefresh";
import { ErrorLine } from "./panelStatus";
import type { FunctionProps } from "./registry";
import { Header, useEnvelope } from "./secPanel";
import { gridCsv, useCsvExport } from "./tableExport";

const LIST_COLUMNS: Column<ExtInfo>[] = [
  { title: "NAME", width: 14, text: (r) => r.name, color: () => "acc" },
  { title: "VERSION", width: 9, text: (r) => r.version ?? "" },
  { title: "AUTHOR", width: 18, text: (r) => r.author ?? "" },
  { title: "LICENSE", width: 10, text: (r) => r.license ?? "", color: () => "dim" },
  { title: "FROM", width: 16, text: (r) => r.source, color: () => "dim" },
  { title: "ADDS", width: 18, text: (r) => r.adds.join(","), color: () => "dim" },
  { title: "STATE", width: 6, text: (r) => r.status, color: (r) => statusClass(r.status) },
  { title: "NOTE", width: 60, text: (r) => r.error ?? r.description, color: (r) => (r.error ? "err" : "dim") },
];

export default function EXT({ panelId, args }: FunctionProps) {
  const cmd = useMemo(() => parseExtArgs(args), [args]);
  if (cmd.mode === "usage") {
    return (
      <div className="fn">
        <div className="line">
          <span className="acc">EXT</span> · {cmd.text}
        </div>
      </div>
    );
  }
  if (cmd.mode === "view") return <ExtView panelId={panelId} name={cmd.name} rest={cmd.rest} />;
  return <ExtListView panelId={panelId} action={cmd.mode === "list" ? null : { kind: cmd.mode, name: cmd.name }} />;
}

function ExtListView({ panelId, action }: { panelId: number; action: { kind: "enable" | "disable"; name: string } | null }) {
  const grid = useRef<GridHandle>(null);
  const [say, setSay] = useState<{ text: string; err: boolean } | null>(null);
  const { env, error, loading, reload } = useEnvelope<ExtList>("list", async () => {
    const d = await extApi.list();
    return { data: d, source: "openterm", as_of: Date.now() / 1000, age_s: 0, stale: false, fallback_from: [] };
  });
  const rows = useMemo(() => env?.data.extensions ?? [], [env]);
  const latest = useLatest({ rows });
  const ran = useRef<string | null>(null);

  const toggle = (name: string, on: boolean) => {
    const done = (text: string, err = false) => {
      setSay({ text, err });
      void reload(true);
    };
    (on ? extApi.enable(name) : extApi.disable(name))
      .then((r) => {
        const x = r.extension;
        done(on ? `ENABLED ${x.name.toUpperCase()} ${x.version ?? ""} BY ${(x.author ?? "?").toUpperCase()} (${x.source.toUpperCase()}) · IT RUNS WITH YOUR PERMISSIONS` : `DISABLED ${x.name.toUpperCase()}`);
      })
      .catch((e: ApiError) => done(`${on ? "ENABLE" : "DISABLE"} ${name.toUpperCase()} FAILED: ${e.message}`, true));
  };

  // `EXT ENABLE name` typed in the command line: do it once, then show the plain list so going back/forward never repeats it.
  useEffect(() => {
    if (!action) return;
    const key = `${action.kind}:${action.name}`;
    if (ran.current === key) return;
    ran.current = key;
    toggle(action.name, action.kind === "enable");
    replaceView(panelId, (v) => ({ ...v, args: ["LIST"] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per typed command
  }, [action?.kind, action?.name]);

  useCsvExport(panelId, () => gridCsv("EXT", LIST_COLUMNS, rows));
  usePanelRefresh(panelId, () => { void reload(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { rows: cur } = latest.current;
        if (navKey(e, grid.current, cur.length)) return true;
        const row = cur[grid.current?.selected() ?? -1];
        if (!row) return false;
        if (e.key === "Enter") {
          if (row.status === "ON") navigate(panelId, { fn: "EXT", args: [row.name], security: undefined });
          else toggle(row.name, true);
          return true;
        }
        if (e.key === "d") {
          toggle(row.name, false);
          return true;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- toggle only uses setters and a stable reload
    [panelId, latest],
  );

  return (
    <div className="fn">
      <Header title="EXTENSIONS" env={env} loading={loading} keys="J/K MOVE · ENTER OPEN OR ENABLE · D DISABLE · E CSV · F5 REFRESH · EXT ENABLE <NAME>" />
      <div className="warn">{env?.data.notice ?? "EXTENSIONS ARE THIRD-PARTY CODE THAT RUNS WITH YOUR PERMISSIONS. EVERYTHING IS OFF UNTIL YOU ENABLE IT."}</div>
      {say && <div className={say.err ? "err" : "acc"}>{say.text}</div>}
      <ErrorLine error={error} hasData={!!env} usage={EXT_USAGE} />
      {env && rows.length === 0 && (
        <div className="dim">NO EXTENSIONS FOUND. PUT A FOLDER WITH extension.yaml IN {env.data.dir ?? "THE DATA FOLDER"} OR INSTALL A PACKAGE IN THE openterm.extensions GROUP. SEE docs/EXTENSIONS.md.</div>
      )}
      <Grid ref={grid} columns={LIST_COLUMNS} rows={rows} />
    </div>
  );
}

function ExtView({ panelId, name, rest }: { panelId: number; name: string; rest: string[] }) {
  const grid = useRef<GridHandle>(null);
  const chart = useRef<ChartHandle>(null);
  const [info, setInfo] = useState<ExtInfo | null>(null);
  const key = `${name}|${rest.join(" ")}`;
  const { env, error, loading, reload } = useEnvelope<ExtPayload>(key, async (fresh) => {
    const list = await extApi.list();
    const x = list.extensions.find((e) => e.name === name);
    setInfo(x ?? null);
    if (!x) throw new ApiError(404, `NO EXTENSION NAMED ${name.toUpperCase()}: EXT LIST SHOWS WHAT IS INSTALLED`, "not_found");
    if (x.status === "OFF") throw new ApiError(403, `EXTENSION ${name.toUpperCase()} IS OFF: TYPE EXT ENABLE ${name.toUpperCase()} (IT IS THIRD-PARTY CODE AND RUNS WITH YOUR PERMISSIONS)`, "forbidden");
    const { route, args } = pickRoute(rest, x.routes.map((r) => r.name));
    return extApi.data(name, route, args, fresh);
  });
  const d = env?.data;
  const section = useMemo(() => (d?.kind === "table" ? tableSection(d) : null), [d]);
  const columns = useMemo(() => (section ? gridColumns(section) : []), [section]);
  const rows: TableRow[] = section?.rows ?? [];
  const series = useMemo(() => (d?.kind === "series" ? seriesBars(d) : null), [d]);
  const latest = useLatest({ rows });
  useCsvExport(panelId, () => (section ? gridCsv(`EXT_${name.toUpperCase()}`, columns, rows) : null));
  usePanelRefresh(panelId, () => { void reload(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.key === "l") {
          navigate(panelId, { fn: "EXT", args: ["LIST"], security: undefined });
          return true;
        }
        return navKey(e, grid.current, latest.current.rows.length);
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <Header title={d?.title || `EXT ${name.toUpperCase()}`} env={env} loading={loading} keys="J/K MOVE · L LIST · E CSV · F5 REFRESH" />
      {info && <div className="dim">{provenance(info)} · RUNS WITH YOUR PERMISSIONS</div>}
      <ErrorLine error={error} hasData={!!env} usage={EXT_USAGE} />
      {info?.status === "ERR" && info.error && <div className="err">EXTENSION ERR: {info.error}</div>}
      {section && rows.length === 0 && !error && <div className="warn">NO ROWS</div>}
      {section && <Grid ref={grid} columns={columns} rows={rows} />}
      {d?.kind === "table" && d.notes?.map((n) => (
        <div key={n} className="summary dim">
          {n}
        </div>
      ))}
      {series && d?.kind === "series" && (
        series.bars.t.length === 0 ? (
          <div className="warn">NO POINTS</div>
        ) : (
          <>
            {series.skipped > 0 && <div className="warn">{series.skipped} EMPTY POINTS SKIPPED, NOT FILLED IN</div>}
            <ChartView key={key} ref={chart} data={series.bars} type="LINE" log={false} readoutLabel={(d.unit || "VALUE").toUpperCase()} />
          </>
        )
      )}
    </div>
  );
}
