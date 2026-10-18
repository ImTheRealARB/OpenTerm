/** News: market top stories (RSS), a security's headlines (Yahoo RSS, GDELT) or a GDELT keyword search. */
import { pollMs } from "../settings/runtime";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { checkNewsItems } from "../command/alerts";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, type Envelope, type NewsItem, type NewsPayload } from "../net/api";
import { newsQuery } from "./newsArgs";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";


interface Row extends NewsItem {
  fresh: boolean;
}

const COLUMNS: Column<Row>[] = [
  { title: "TIME", width: 8, text: (r) => fmtTime(r.published ? r.published * 1000 : null), color: (r) => (r.fresh ? "acc" : "dim") },
  { title: "SOURCE", width: 16, text: (r) => (r.publisher ?? "").toUpperCase(), color: () => "dim" },
  { title: "HEADLINE", width: 160, text: (r) => r.title, color: (r) => (r.fresh ? "acc" : "fg") },
];

function openArticle(url: string): void {
  // Article bodies are never fetched or shown here: the publisher's page opens in a new tab.
  window.open(url, "_blank", "noopener,noreferrer");
}

export default function N({ panelId, args, security }: FunctionProps) {
  const query = useMemo(() => newsQuery(args, security), [args, security]);
  const [env, setEnv] = useState<Envelope<NewsPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState(0);
  const firstIds = useRef<Set<string> | null>(null);
  const grid = useRef<GridHandle>(null);

  const load = useCallback(
    (fresh: boolean) => {
      setLoading(true);
      const params = query.kind === "symbol" ? { symbol: query.symbol } : query.kind === "keyword" ? { q: query.q } : {};
      return api
        .news(params, fresh)
        .then((e) => {
          setEnv(e);
          setError(null);
          if (query.kind !== "keyword") checkNewsItems(query.kind === "symbol" ? query.symbol.toUpperCase() : null, e.data.items);
        })
        .catch((e: ApiError) => setError(e))
        .finally(() => setLoading(false));
    },
    [query],
  );

  useEffect(() => {
    firstIds.current = null;
    setEnv(null);
    void load(false);
    const t = setInterval(() => void load(false), pollMs("news"));
    return () => clearInterval(t);
  }, [load]);

  const rows = useMemo<Row[]>(() => {
    const items = env?.data.items ?? [];
    if (!firstIds.current && items.length) firstIds.current = new Set(items.map((i) => i.id));
    const first = firstIds.current;
    return items.map((i) => ({ ...i, fresh: !!first && !first.has(i.id) }));
  }, [env]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => gridCsv("NEWS", COLUMNS, rows, [{ title: "URL", text: (r) => r.url }]));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r) openArticle(r.url);
            return true;
          }
          case "F5":
            void load(true);
            return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const title = query.kind === "top" ? "TOP NEWS" : query.kind === "symbol" ? `NEWS: ${query.symbol}` : `NEWS SEARCH: ${query.q}`;
  const d = env?.data;
  const pick = rows[Math.min(sel, rows.length - 1)];
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">{title}</span>
        {d && ` · ${d.items.length} HEADLINES · ${(env.source ?? "").toUpperCase()}`}
        {env?.stale && <span className="warn"> · STALE {fmtAge(env.age_s)}</span>}
        {d && d.failed.length > 0 && <span className="warn"> · NOT ANSWERING: {d.failed.join(", ")}</span>}
        {loading && <span className="dim"> · LOADING…{query.kind === "keyword" && " (GDELT CAN TAKE 5-15 S)"}</span>}
        <span className="dim"> · J/K MOVE · ENTER OPEN ARTICLE · E CSV · F5 REFRESH</span>
      </div>
      {error && (
        <div className="err">
          {error.message}
          {error.detail && <span className="dim"> ({error.detail})</span>}
          {env && <span className="warn"> · SHOWING THE LAST HEADLINES</span>}
        </div>
      )}
      {rows.length > 0 || !error ? <Grid ref={grid} columns={COLUMNS} rows={rows} onSelect={setSel} /> : null}
      {pick && (
        <div className="summary">
          <span className="dim">{pick.publisher} · </span>
          {pick.summary ?? <span className="dim">NO SUMMARY IN THE FEED</span>}
        </div>
      )}
    </div>
  );
}
