/**
 * HOME: the page OpenTerm opens on. A ticker tape on top, then a dense grid of blocks: market numbers (indices, FX,
 * commodities, crypto, rates) and the day's headlines by section (each row: source, age, title).
 *
 * Numbers: ONE snapshot request + ONE subscription for the tape and every block (home/useQuoteMap.ts); ticks then edit the
 * text of the visible numbers directly (home/liveCells.tsx). Headlines: one /api/news request per block, each with its own
 * honest ERR line (message and source/age) when it fails; nothing is invented.
 * Keys: J/K rows, H/L blocks, G/Shift+G first/last, Enter opens (headline: the article in a new tab; number: its chart in a
 * new panel), F5 refreshes. Everything is also clickable.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { execute } from "../command/execute";
import { fmtAge } from "../format";
import { BLOCKS, homeSymbols, mergeNews, newsQuery, type NewsBlock, type QuoteBlock, type QuoteItem } from "../home/homeConfig";
import { firstBlock, moveNav, type Pos } from "../home/homeNav";
import { LiveCell, quoteFlag } from "../home/liveCells";
import { TickerTape } from "../home/TickerTape";
import { useQuoteMap } from "../home/useQuoteMap";
import "../home/home.css";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, type NewsItem } from "../net/api";
import { pollMs, settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { useLatest, type QRow } from "./quoteRows";
import type { FunctionProps } from "./registry";

/** What one news block currently shows. */
interface NewsState {
  items: NewsItem[];
  /** The answering source(s) and how old the answer is; both come from the response envelope. */
  source: string;
  ageS: number;
  stale: boolean;
  /** Set when EVERY request of the block failed (nothing to show). */
  error?: string;
  /** Sections that failed while another one answered (a block of two sections). */
  failed: string[];
  loading: boolean;
}

const NEWS_BLOCKS = BLOCKS.filter((b): b is NewsBlock => b.kind === "news");
const LOADING: NewsState = { items: [], source: "", ageS: 0, stale: false, failed: [], loading: true };

const errText = (e: unknown): string => (e instanceof ApiError ? e.message + (e.detail ? ` (${e.detail})` : "") : e instanceof Error ? e.message : String(e));

/** Fetches every news block (all at once, each independent). `fresh` skips the short client cache (F5). */
function loadNews(fresh: boolean, alive: () => boolean, put: (id: string, s: NewsState) => void): void {
  for (const b of NEWS_BLOCKS) {
    void Promise.allSettled(b.sections.map((s) => api.news(newsQuery(s, b.limit), fresh))).then((results) => {
      if (!alive()) return;
      const ok = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
      const bad = results.flatMap((r, i) => (r.status === "rejected" ? [{ section: b.sections[i] ?? "top", why: errText(r.reason) }] : []));
      if (!ok.length) {
        put(b.id, { ...LOADING, loading: false, error: bad[0]?.why ?? "NO ANSWER" });
        return;
      }
      put(b.id, {
        items: mergeNews(ok.map((e) => e.data.items), b.limit),
        source: [...new Set(ok.map((e) => (e.source ?? "").toUpperCase()).filter(Boolean))].join("+"),
        ageS: Math.max(...ok.map((e) => e.age_s)),
        stale: ok.some((e) => e.stale),
        failed: bad.map((x) => x.section),
        loading: false,
      });
    });
  }
}

function openArticle(url: string): void {
  // Article bodies are never fetched or shown here: the publisher's page opens in a new tab.
  window.open(url, "_blank", "noopener,noreferrer");
}
/** A number's chart opens in a NEW panel so the page stays where it is (HOME brings it back anyway). */
const openChart = (symbol: string): void => void execute(`${symbol} GP`, { newPanel: true });

function QuoteRows({ block, quotes, bi, pos, pick }: { block: QuoteBlock; quotes: ReadonlyMap<string, QRow>; bi: number; pos: Pos; pick: (b: number, r: number, open: boolean) => void }) {
  let r = -1; // index among the selectable rows (headings are skipped)
  return (
    <>
      {block.rows.map((row) => {
        if ("head" in row) {
          return (
            <div key={`h-${row.head}`} className="hb-sub">
              {row.head}
            </div>
          );
        }
        const it: QuoteItem = row;
        const my = ++r;
        const q = quotes.get(it.symbol);
        const flag = quoteFlag(q);
        const on = pos.b === bi && pos.r === my;
        return (
          <div key={it.symbol} className={"hr hq" + (on ? " on" : "")} data-testid={`home-q-${it.symbol}`} aria-selected={on} onClick={() => pick(bi, my, true)} title={q?.error ?? q?.q?.name ?? it.symbol}>
            <span className="hq-l">{it.label}</span>
            {flag && <span className={flag.cls}>{flag.text}</span>}
            <LiveCell symbol={it.symbol} kind="last" row={q} className="hq-v" />
            <LiveCell symbol={it.symbol} kind="pct" row={q} className="hq-p" />
          </div>
        );
      })}
    </>
  );
}

function NewsRows({ s, bi, pos, pick }: { s: NewsState; bi: number; pos: Pos; pick: (b: number, r: number, open: boolean) => void }) {
  const nowS = Date.now() / 1000;
  return (
    <>
      {s.loading && <div className="hb-note dim">LOADING…</div>}
      {s.error && <div className="hb-note err">ERR {s.error} (F5 RETRIES)</div>}
      {!s.loading && !s.error && s.items.length === 0 && <div className="hb-note dim">NO HEADLINES</div>}
      {s.items.map((it, i) => {
        const on = pos.b === bi && pos.r === i;
        return (
          <a key={it.id} href={it.url} target="_blank" rel="noopener noreferrer" className={"hr hn" + (on ? " on" : "")} aria-selected={on} title={it.title} onClick={() => pick(bi, i, false)}>
            <span className="hn-s">{(it.publisher ?? it.source ?? "").toUpperCase()}</span>
            <span className="hn-a">{it.published ? fmtAge(Math.max(0, nowS - it.published)) : "–"}</span>
            <span className="hn-t">{it.title}</span>
          </a>
        );
      })}
    </>
  );
}

export default function HOME({ panelId }: FunctionProps) {
  const tapeSymbols = useStore(settingsStore, (s) => s.tapeSymbols);
  const globalTape = useStore(settingsStore, (s) => s.tape);
  const symbols = useMemo(() => homeSymbols(tapeSymbols), [tapeSymbols]);
  const quotes = useQuoteMap(symbols);

  const [news, setNews] = useState<Record<string, NewsState>>({});
  const aliveRef = useRef(true);
  const refresh = (fresh: boolean) => loadNews(fresh, () => aliveRef.current, (id, s) => setNews((n) => ({ ...n, [id]: s })));
  useEffect(() => {
    aliveRef.current = true;
    refresh(false);
    const t = setInterval(() => refresh(false), pollMs("news"));
    return () => {
      aliveRef.current = false;
      clearInterval(t);
    };
  }, []);

  // How many selectable rows each block has right now (for the cursor).
  const counts = BLOCKS.map((b) => (b.kind === "quotes" ? b.rows.filter((r) => "symbol" in r).length : (news[b.id]?.items.length ?? 0)));
  const [pos, setPos] = useState<Pos>({ b: 0, r: 0 });
  // The cursor starts on the first block that has rows (numbers load before headlines, but both lists can be empty for a moment).
  const start = firstBlock(counts);
  const cur: Pos = counts[pos.b] === 0 ? { b: start, r: 0 } : pos;

  const grid = useRef<HTMLDivElement>(null);
  useEffect(() => {
    grid.current?.querySelector(".hr.on")?.scrollIntoView({ block: "nearest" });
  }, [cur.b, cur.r]);

  /** Activates the row under (b, r): a headline opens its article, a number opens its chart. */
  const activate = (b: number, r: number) => {
    const blk = BLOCKS[b];
    if (blk.kind === "news") {
      const it = news[blk.id]?.items[r];
      if (it) openArticle(it.url);
    } else {
      const items = blk.rows.filter((x): x is QuoteItem => "symbol" in x);
      if (items[r]) openChart(items[r].symbol);
    }
  };
  const pick = (b: number, r: number, open: boolean) => {
    setPos({ b, r });
    if (open) activate(b, r);
  };

  const live = useLatest({ counts, cur, activate });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { counts: c, cur: p, activate: act } = live.current;
        if (e.key === "Enter") {
          act(p.b, p.r);
          return true;
        }
        if (e.key === "F5") {
          refresh(true);
          return true;
        }
        const next = moveNav(c, p, e.key);
        if (!next) return false;
        setPos(next);
        return true;
      }),
    [panelId, live],
  );

  const date = new Date().toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" }).replace(/,/g, "").toUpperCase();
  return (
    <div className="fn home" data-testid="home">
      {/* With the tape also in the top bar, a second copy here would just repeat it. */}
      {!globalTape && <TickerTape symbols={tapeSymbols} quotes={quotes} />}
      <div className="line">
        <span className="home-date">HOME · {date}</span>
        <span className="dim legend"> · J/K ROWS · H/L BLOCKS · ENTER OPEN · F5 REFRESH · TAPE ADD|DEL SYM EDITS THE TAPE · SETTINGS STARTUP LAYOUT KEEPS YOUR PANELS INSTEAD</span>
      </div>
      <div className="home-grid" ref={grid}>
        {BLOCKS.map((b, bi) => {
          const n = b.kind === "news" ? (news[b.id] ?? LOADING) : null;
          return (
            <section key={b.id} className={"hb" + (cur.b === bi ? " on" : "")} data-testid={`home-block-${b.id}`}>
              <div className="hb-h">
                <span>{b.title}</span>
                {n && !n.loading && !n.error && (
                  <span className="hb-meta dim">
                    {n.source} {fmtAge(n.ageS)}
                    {n.stale && <span className="warn"> STALE</span>}
                    {n.failed.length > 0 && <span className="err"> ERR {n.failed.join(",").toUpperCase()}</span>}
                  </span>
                )}
              </div>
              {b.kind === "quotes" ? (
                <QuoteRows block={b} quotes={quotes} bi={bi} pos={cur} pick={pick} />
              ) : (
                <NewsRows s={n!} bi={bi} pos={cur} pick={pick} />
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
