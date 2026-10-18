/**
 * SECF: security finder. `SECF <text>` ranks the EQS screener universe plus Yahoo search hits with a typo-tolerant scorer (secfScore.ts);
 * `SECF <ISIN|CUSIP|SEDOL|FIGI:id ...>` maps identifiers to listings through OpenFIGI (keyless, server side). Enter opens DES.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtBig } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, api9, worldApi, type Envelope, type FigiItem, type FigiListing, type FigiResult, type ScreenerPayload, type SearchHit } from "../net/api";
import { navigate } from "../state/workspace";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { identsOf, yahooSymbol } from "./secfIds";
import { candidatesFromUniverse, mergeSearch, rank, type Hit } from "./secfScore";
import { gridCsv, useCsvExport } from "./tableExport";

const USAGE = "SECF APPLE · SECF MICROSFT · SECF RELIANCE · SECF US0378331005 · SECF 037833100 · SECF 2046251 · SECF FIGI:BBG000B9XRY4";
const LIMIT = 200;

/** One line of an identifier lookup: an OpenFIGI listing, or the reason an identifier has none. */
interface FigiRow {
  id: string;
  kind: string;
  status: FigiItem["status"];
  message: string | null;
  listing: FigiListing | null;
}

function figiRows(items: FigiItem[]): FigiRow[] {
  return items.flatMap((it): FigiRow[] =>
    it.listings.length
      ? it.listings.map((l) => ({ id: it.id, kind: it.kind, status: it.status, message: null, listing: l }))
      : [{ id: it.id, kind: it.kind, status: it.status, message: it.message, listing: null }],
  );
}

export default function SECF({ panelId, args }: FunctionProps) {
  const query = args.join(" ").trim();
  const idents = useMemo(() => identsOf(query), [query]);
  const [uni, setUni] = useState<Envelope<ScreenerPayload> | null>(null);
  const [search, setSearch] = useState<Envelope<SearchHit[]> | null>(null);
  const [figi, setFigi] = useState<Envelope<FigiResult> | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [reload, setReload] = useState(0);
  const grid = useRef<GridHandle>(null);

  useEffect(() => {
    let live = true;
    setMsg("");
    setErrors([]);
    if (!query) {
      setLoading(false);
      return;
    }
    const fresh = reload > 0;
    const fail = (what: string) => (e: unknown) => {
      const err = e as ApiError;
      if (live) setErrors((x) => [...x, `${what}: ${err.message}${err.detail ? ` (${err.detail})` : ""}`]);
    };
    setLoading(true);
    if (idents) {
      setUni(null);
      setSearch(null);
      void worldApi
        .figi(query, fresh)
        .then((e) => live && setFigi(e))
        .catch((e) => {
          if (live) setFigi(null);
          fail("OPENFIGI")(e);
        })
        .finally(() => live && setLoading(false));
    } else {
      setFigi(null);
      const u = api9.screener(fresh).then((e) => live && setUni(e)).catch((e) => {
        if (live) setUni(null);
        fail("EQS UNIVERSE")(e);
      });
      const s = api.search(query).then((e) => live && setSearch(e)).catch((e) => {
        if (live) setSearch(null);
        fail("YAHOO SEARCH")(e);
      });
      void Promise.all([u, s]).finally(() => live && setLoading(false));
    }
    return () => {
      live = false;
    };
  }, [query, idents, reload]);

  const hits = useMemo<Hit[]>(() => {
    if (idents || !query || (!uni && !search)) return [];
    const base = uni ? candidatesFromUniverse(uni.data) : [];
    return rank(search ? mergeSearch(base, search.data) : base, query, LIMIT);
  }, [idents, query, uni, search]);
  const rows = useMemo(() => (figi ? figiRows(figi.data.items) : []), [figi]);

  const hitCols = useMemo<Column<Hit>[]>(
    () => [
      { title: "SYMBOL", width: 12, text: (r) => r.symbol, color: () => "acc" },
      { title: "NAME", width: 38, text: (r) => r.name },
      { title: "EXCH", width: 6, text: (r) => r.exchange ?? "", color: () => "dim" },
      { title: "TYPE", width: 9, text: (r) => r.type ?? "", color: () => "dim" },
      { title: "SECTOR", width: 22, text: (r) => r.sector ?? "", color: () => "dim" },
      { title: "MKT CAP", width: 8, align: "right", text: (r) => (r.mcap == null ? "" : fmtBig(r.mcap)) },
      { title: "SRC", width: 6, text: (r) => r.src, color: () => "dim" },
    ],
    [],
  );
  const figiCols = useMemo<Column<FigiRow>[]>(
    () => [
      { title: "ID", width: 14, text: (r) => r.id, color: () => "acc" },
      { title: "KIND", width: 5, text: (r) => r.kind, color: () => "dim" },
      { title: "STATUS", width: 15, text: (r) => r.status, color: (r) => (r.status === "FOUND" ? "fg" : "warn") },
      { title: "TICKER", width: 10, text: (r) => r.listing?.ticker ?? "" },
      { title: "NAME", width: 30, text: (r) => r.listing?.name ?? r.message ?? "" },
      { title: "EXCH", width: 5, text: (r) => r.listing?.exch_code ?? "", color: () => "dim" },
      { title: "TYPE", width: 16, text: (r) => r.listing?.security_type ?? "", color: () => "dim" },
      { title: "FIGI", width: 13, text: (r) => r.listing?.figi ?? "" },
      { title: "COMPOSITE", width: 13, text: (r) => r.listing?.composite_figi ?? "", color: () => "dim" },
    ],
    [],
  );

  const count = idents ? rows.length : hits.length;
  const latest = useLatest({ idents, rows, hits });
  useCsvExport(panelId, () => {
    if (!query) return null;
    return idents && figi ? gridCsv(`SECF_${query.replace(/\W+/g, "_")}`, figiCols, rows) : !idents && (uni || search) ? gridCsv(`SECF_${query.replace(/\W+/g, "_")}`, hitCols, hits) : null;
  });

  const open = useCallback(
    (symbol: string) => navigate(panelId, { fn: "DES", security: { symbol }, args: [] }),
    [panelId],
  );
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.idents ? cur.rows.length : cur.hits.length)) return true;
        if (e.key === "F5") {
          setReload((n) => n + 1);
          return true;
        }
        if (e.key !== "Enter") return false;
        const i = g?.selected() ?? -1;
        if (cur.idents) {
          const l = cur.rows[i]?.listing;
          if (!l) return true;
          const sym = yahooSymbol(l.exch_code, l.ticker);
          if (sym) open(sym);
          else setMsg(`NO OPENTERM SYMBOL FOR OPENFIGI EXCHANGE CODE ${l.exch_code ?? "?"} (TICKER ${l.ticker ?? "?"}); TYPE THE SYMBOL YOURSELF`);
        } else if (cur.hits[i]) {
          open(cur.hits[i].symbol);
        }
        return true;
      }),
    [panelId, latest, open],
  );

  const env = idents ? figi : uni;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">SECF</span>
        {query ? ` ${query.toUpperCase()}` : ""}
        {query && (idents ? <span className="dim"> · IDENTIFIER LOOKUP · OPENFIGI</span> : <span className="dim"> · NAME SEARCH · EQS UNIVERSE + YAHOO SEARCH · 1 TYPO ALLOWED</span>)}
        {query && !loading && (errors.length === 0 || count > 0) && <span className="acc"> · {count} {idents ? "LINES" : "MATCH"}</span>}
        {env && <span className="dim"> · {(env.source ?? "").toUpperCase()}</span>}
        {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · J/K MOVE · ENTER DES · E CSV · F5 REFRESH</span>
      </div>
      {!query && <div className="warn">TYPE A NAME, A TICKER OR AN IDENTIFIER. EXAMPLES: {USAGE}</div>}
      {errors.map((x) => (
        <div key={x} className="err">{x}</div>
      ))}
      {idents && figi && <div className="dim">{figi.data.note}</div>}
      {msg && <div className="warn">{msg}</div>}
      {query && !loading && count === 0 && errors.length === 0 && <div className="warn">NOTHING MATCHES {query.toUpperCase()}</div>}
      {idents ? <Grid ref={grid} columns={figiCols} rows={rows} /> : <Grid ref={grid} columns={hitCols} rows={hits} />}
    </div>
  );
}
