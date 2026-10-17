import { useEffect, useState } from "react";
import { ApiError, api, type SourcesPayload } from "../net/api";
import { sources } from "../net/sources";
import type { FunctionProps } from "./registry";
import { useCsvExport } from "./tableExport";

const ms = (v: number | null) => (v == null ? "—" : v.toFixed(0));
const ago = (s: number | null) => (s == null ? "—" : s < 60 ? `${s.toFixed(0)}S` : `${(s / 60).toFixed(0)}M`);
const cls = (status: string) =>
  status === "OK" ? "up" : status === "DOWN" ? "err" : status === "DEGRADED" ? "warn" : "dim";

export default function Sources({ panelId }: FunctionProps) {
  const [s, setS] = useState<SourcesPayload | null>(null);
  useCsvExport(panelId, () =>
    s
      ? {
          name: "SOURCES",
          header: ["PROVIDER", "STATUS", "P50_MS", "P95_MS", "CALLS", "ERRORS", "TOKENS", "RATE_PER_S", "LAST_OK_AGE_S", "LAST_ERROR"],
          rows: s.providers.map((p) => [p.name, p.status, p.latency_p50_ms, p.latency_p95_ms, p.calls, p.errors, p.tokens_remaining, p.rate_per_s, p.last_ok_age_s, p.last_error]),
        }
      : null,
  );
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .sources()
        .then((v) => {
          sources.set(() => v); // keep the status bar consistent with this screen
          if (alive) {
            setS(v);
            setErr(null);
          }
        })
        .catch((e: ApiError) => alive && setErr(e.message));
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (!s) return <div className={err ? "err" : "dim"}>{err ?? "LOADING…"}</div>;
  return (
    <div>
      <h2>DATA SOURCES {err && <span className="err">STALE: {err}</span>}</h2>
      {s.fixtures && <div className="warn">FIXTURE MODE: REPLAYING RECORDED RESPONSES, NOT LIVE DATA</div>}
      <table className="t">
        <colgroup>
          <col style={{ width: 80 }} />
          <col style={{ width: 80 }} />
          <col style={{ width: 60 }} />
          <col style={{ width: 60 }} />
          <col style={{ width: 70 }} />
          <col style={{ width: 70 }} />
          <col style={{ width: 60 }} />
          <col />
        </colgroup>
        <thead>
          <tr>
            <th>PROVIDER</th>
            <th>STATUS</th>
            <th className="n">P50 MS</th>
            <th className="n">P95 MS</th>
            <th className="n">CALLS/ERR</th>
            <th className="n">TOKENS</th>
            <th className="n">LAST OK</th>
            <th>LAST ERROR</th>
          </tr>
        </thead>
        <tbody>
          {s.providers.map((p) => (
            <tr key={p.name}>
              <td className="acc">{p.name.toUpperCase()}</td>
              <td className={cls(p.status)}>
                {p.status}
                {p.status === "DOWN" && ` ${p.down_for_s.toFixed(0)}S`}
              </td>
              <td className="n">{ms(p.latency_p50_ms)}</td>
              <td className="n">{ms(p.latency_p95_ms)}</td>
              <td className="n">
                {p.calls}/{p.errors}
              </td>
              <td className="n">
                {p.tokens_remaining.toFixed(0)} @{p.rate_per_s}/S
              </td>
              <td className="n">{ago(p.last_ok_age_s)}</td>
              <td className="dim">{p.last_error ? `${p.last_error} (${ago(p.last_error_age_s)} AGO)` : ""}</td>
            </tr>
          ))}
          {s.keyed.map((k) => (
            <tr key={k.name}>
              <td className="dim">{k.name.toUpperCase()}</td>
              <td className={k.status === "RETIRED" ? "err" : "warn"} colSpan={2}>
                {k.status}
              </td>
              <td className="dim" colSpan={5}>
                {k.note}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>FALLBACK ORDER</h2>
      {Object.entries(s.order).map(([cap, names]) => (
        <div key={cap}>
          <span className="dim">{cap.toUpperCase().padEnd(8)}</span> {names.join(" → ").toUpperCase()}
        </div>
      ))}
      <h2>CACHE</h2>
      <div>
        HIT {s.cache.hit_pct == null ? "—" : s.cache.hit_pct.toFixed(0) + "%"} · FRESH {s.cache.fresh_hits} · STALE{" "}
        {s.cache.stale_hits} · MISS {s.cache.misses} · IN FLIGHT {s.cache.inflight} · MEM {s.cache.mem_entries}
      </div>
      <h2>COVERAGE AND TERMS</h2>
      {s.providers.map((p) => (
        <div key={p.name}>
          <span className="acc">{p.label}</span> <span className="dim">{p.markets}. {p.terms}</span>
        </div>
      ))}
    </div>
  );
}
