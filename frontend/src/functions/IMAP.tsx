/**
 * IMAP: heat maps. Tiles are sized by market cap (or total assets) and coloured by today's % change; groups are sectors, industries,
 * countries or fund categories. Three universes (imapUniverses.ts), one drawing (ImapBoard.tsx):
 *
 *   IMAP [SECTOR|INDUSTRY|COUNTRY] [N=3000] [EQS filter]   the US equity universe (EQS data)
 *   IMAP CRYPTO [N=50]                                     the crypto board: size = market cap, colour = 24 hour change
 *   IMAP ETF [N=150] [FSRC filter: FEE<0.2 CAT=TECH]       the biggest ETFs of the FSRC table: size = total assets
 *   IMAP NIFTY | NIFTY500                                  NSE index members, equal tiles (no weights in NSE's list), by industry
 *
 * This file only loads each universe's data and words its status; keys, layout and painting live in ImapBoard.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { fmtAge } from "../format";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import { scanApi } from "../net/scanApi";
import type { Coin, Envelope, ScreenerPayload } from "../net/types";
import { parseFilter } from "./eqsFilter";
import { buildImap, parseImapArgs } from "./imapData";
import { buildCrypto, buildEtf, buildNifty, CRYPTO_LIMIT, ETF_LIMIT, ETF_MAX, parseUniverse, takeLimit, topFunds, usView } from "./imapUniverses";
import { ImapBoard } from "./ImapBoard";
import type { NiftyMember } from "./imapUniverses";
import { parseFsrcFilter, screenFsrc } from "./fsrcFilter";
import { usePanelRefresh } from "./panelRefresh";
import { EnvStatus, ErrorLine } from "./panelStatus";
import type { FunctionProps } from "./registry";
import { useFsrc } from "./useFsrc";
import { useQuotePct } from "./useQuotePct";

export default function IMAP(props: FunctionProps) {
  const { universe, rest } = parseUniverse(props.args);
  if (universe === "CRYPTO") return <CryptoMap panelId={props.panelId} args={rest} />;
  if (universe === "ETF") return <EtfMap panelId={props.panelId} args={rest} />;
  if (universe === "NIFTY" || universe === "NIFTY500") return <NiftyMap panelId={props.panelId} args={rest} index={universe === "NIFTY" ? "NIFTY50" : "NIFTY500"} />;
  return <UsMap panelId={props.panelId} args={props.args} />;
}

interface MapProps {
  panelId: number;
  args: string[];
}

// ---------------------------------------------------------------------------------------------------------------- US equities
function UsMap({ panelId, args }: MapProps) {
  const [env, setEnv] = useState<Envelope<ScreenerPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return marketApi
      .screener(fresh)
      .then((e) => {
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    void load(false);
  }, [load]);
  usePanelRefresh(panelId, () => { void load(true); });

  const opts = useMemo(() => parseImapArgs(args), [args]);
  const view = useMemo(() => (env ? usView(buildImap(env.data, parseFilter(opts.rest), opts)) : null), [env, opts]);
  const u = env?.data;
  return (
    <ImapBoard
      panelId={panelId} label={opts.by} rest={opts.rest} view={view}
      sizeWord="MARKET CAP" sizeTitle="MKT CAP" sizeShort="MCAP" csvName={`IMAP_${opts.by}_${args.join("_") || "ALL"}`}
      noSizeText="ROWS WITHOUT A MARKET CAP HAVE NO TILE" limit={opts.limit} argsKey={args.join(" ")}
      status={
        <>
          {u && <span className="dim"> · {u.source.toUpperCase()}{u.as_of_text ? ` · ${u.as_of_text.toUpperCase()}` : ""}</span>}
          {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
          {loading && <span className="dim"> · LOADING…</span>}
        </>
      }
      notes={error && <div className="err">{error.message}{error.detail ? ` (${error.detail})` : ""}. F5 TO RETRY.</div>}
    />
  );
}

// -------------------------------------------------------------------------------------------------------------------- crypto
function CryptoMap({ panelId, args }: MapProps) {
  const [env, setEnv] = useState<Envelope<{ vs: string; coins: Coin[] }> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return marketApi
      .crypto("USD", fresh)
      .then((e) => {
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    void load(false);
  }, [load]);
  usePanelRefresh(panelId, () => { void load(true); });

  const { limit, rest } = useMemo(() => takeLimit(args, CRYPTO_LIMIT, CRYPTO_LIMIT), [args]);
  const view = useMemo(() => (env ? buildCrypto(env.data.coins, limit) : null), [env, limit]);
  return (
    <ImapBoard
      panelId={panelId} label="CRYPTO" rest={rest} view={view}
      sizeWord="MARKET CAP" sizeTitle="MKT CAP" sizeShort="MCAP" colourWord="% CHANGE IN 24 HOURS" csvName={`IMAP_CRYPTO_${args.join("_") || "ALL"}`}
      noSizeText="COINS WITHOUT A MARKET CAP FROM THIS SOURCE HAVE NO TILE" limit={limit} argsKey={args.join(" ")}
      status={<EnvStatus env={env} loading={loading} />}
      notes={<ErrorLine error={error} hasData={env !== null} />}
    />
  );
}

// ------------------------------------------------------------------------------------------------------------------------ ETFs
function EtfMap({ panelId, args }: MapProps) {
  const { rows: funds, env, error, loading, reload } = useFsrc();
  const { limit, rest } = useMemo(() => takeLimit(args, ETF_LIMIT, ETF_MAX), [args]);
  const d = env?.data;
  // The FSRC filter narrows the funds first (`IMAP ETF CAT=TECH FEE<0.2`), then the biggest `limit` of them get tiles.
  const filtered = useMemo(() => screenFsrc(funds, parseFsrcFilter(rest), d?.state === "complete"), [funds, rest, d?.state]);
  const symbols = useMemo(() => topFunds(filtered.rows, limit).map((f) => f[0]), [filtered, limit]);
  const quotes = useQuotePct(symbols);
  const view = useMemo(() => (d ? buildEtf(filtered.rows, quotes.pct, limit) : null), [d, filtered, quotes.pct, limit]);
  usePanelRefresh(panelId, () => {
    reload();
    quotes.reload();
  });

  // A tile whose symbol was never asked about is waiting for its quote; one that was asked and got nothing back has none.
  const waiting = view ? view.rows.filter((r) => !quotes.pct.has(r.sym)).length : 0;
  const noQuote = view ? view.rows.filter((r) => quotes.pct.get(r.sym) === null).length : 0;
  return (
    <ImapBoard
      panelId={panelId} label="ETF" rest={rest} view={view}
      sizeWord="TOTAL ASSETS" sizeTitle="TOTAL ASSETS" sizeShort="AUM" csvName={`IMAP_ETF_${args.join("_") || "ALL"}`}
      noSizeText="FUNDS WITHOUT TOTAL ASSETS HAVE NO TILE" limit={limit} argsKey={args.join(" ")}
      status={<EnvStatus env={env} loading={loading} />}
      notes={
        <>
          {d?.partial && (
            <div className="warn" data-testid="imap-etf-partial">
              FUND DATA STILL LOADING: {d.loaded.toLocaleString("en-US")} OF {d.universe.toLocaleString("en-US")} FUNDS (PARTIAL): A BIGGER FUND MAY NOT BE ON THE MAP YET
            </div>
          )}
          {waiting > 0 && <div className="dim">{waiting} TILES AWAIT THEIR DAY CHANGE (NEUTRAL COLOUR)</div>}
          {noQuote > 0 && <div className="dim">{noQuote} TILES HAVE NO QUOTE FROM THE QUOTE SOURCE (NEUTRAL COLOUR)</div>}
          {filtered.errors.length > 0 && <div className="err">{filtered.errors.join(" · ")}</div>}
          {quotes.error && <div className="err">QUOTES: {quotes.error.message}</div>}
          <ErrorLine error={error} hasData={funds.length > 0} />
          {!d && !error && <div className="dim">LOADING THE ETF LIST…</div>}
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------------------------------- NIFTY
function NiftyMap({ panelId, args, index }: MapProps & { index: string }) {
  const [members, setMembers] = useState<NiftyMember[] | null>(null);
  const [source, setSource] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    return scanApi
      .nifty(index)
      .then((r) => {
        setMembers(r.rows);
        setSource(r.source);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, [index]);
  useEffect(() => {
    void load();
  }, [load]);

  const symbols = useMemo(() => (members ?? []).map((m) => m.symbol), [members]);
  const quotes = useQuotePct(symbols);
  const view = useMemo(() => (members ? buildNifty(members, quotes.pct) : null), [members, quotes.pct]);
  usePanelRefresh(panelId, () => {
    void load();
    quotes.reload();
  });
  const waiting = view ? view.rows.filter((r) => !quotes.pct.has(r.sym)).length : 0;
  const noQuote = view ? view.rows.filter((r) => quotes.pct.get(r.sym) === null).length : 0;
  return (
    <ImapBoard
      panelId={panelId} label={index} rest={args} view={view}
      sizeWord="EQUAL (NSE'S LIST HAS NO WEIGHTS OR MARKET CAPS)" sizeTitle="EQUAL TILE" sizeShort="" csvName={`IMAP_${index}`}
      noSizeText="" limit={symbols.length} argsKey={`${index} ${args.join(" ")}`}
      status={
        <>
          {source && <span className="dim"> · {source}</span>}
          {loading && <span className="dim"> · LOADING…</span>}
        </>
      }
      notes={
        <>
          {waiting > 0 && <div className="dim">{waiting} TILES AWAIT THEIR DAY CHANGE (NEUTRAL COLOUR)</div>}
          {noQuote > 0 && <div className="dim">{noQuote} TILES HAVE NO QUOTE FROM THE QUOTE SOURCE (NEUTRAL COLOUR)</div>}
          {quotes.error && <div className="err">QUOTES: {quotes.error.message}</div>}
          <ErrorLine error={error} hasData={members !== null} />
        </>
      }
    />
  );
}
