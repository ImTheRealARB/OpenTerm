/**
 * ORD (Phase 18 step 1): the order ticket, the blotter, the mandate and the kill switch. Loopback only; the AI has no route to any of it.
 *
 * Paper is the default (`ORD`, `ORD PAPER`). `ORD ALPACA` and `ORD KITE` are LIVE: the banner says REAL MONEY, live orders must first be
 * switched on (L, typed phrase), the mandate (M) must allow the order, and the order is sent in two steps: Enter reviews it (the server
 * answers with the mandate check and a one-time confirm token for exactly that order), then Y (paper) or the typed symbol + Enter (live)
 * sends it with that token. Nothing on this panel carries a "mode": the broker slot decides it on the server.
 *
 * Keys (outside the fields): E edit the ticket · B broker · S side · T type · G time in force · Enter review · Y confirm paper ·
 * Esc drop the review · X KILL (cancel every open order, block new ones) · U release the kill switch · L live on/off · M mandate ·
 * C cancel the selected open order (Up/Down select) · I add today's fills to a portfolio · R reload.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { refreshPortfolios } from "../command/portfolios";
import { registerPanelKeys } from "../keys/panelKeys";
import type { ApiError } from "../net/core";
import { LIVE_PHRASE, ordersApi, type Blotter, type LedgerView, type OrderBroker, type OrdersStatus, type Preview } from "../net/ordersApi";
import { usePanelRefresh } from "./panelRefresh";
import type { FunctionProps } from "./registry";
import { ageText, BROKER_NAME, BROKER_ORDER, confirmReady, confirmWord, EMPTY_DRAFT, mandateText, money, ORD_USAGE, parseMandate, parseOrdArgs, SLOT_MODE, toBody, type Draft } from "./ordModel";

type Msg = { text: string; cls: string } | null;
const TYPES: Draft["type"][] = ["market", "limit", "stop"];
const TIFS: Draft["tif"][] = ["day", "gtc", "ioc"];
const cycle = <T,>(list: T[], cur: T): T => list[(list.indexOf(cur) + 1) % list.length];

export default function ORD({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseOrdArgs(args), [args]);
  const [draft, setDraft] = useState<Draft>(() => ("error" in parsed ? EMPTY_DRAFT : parsed));
  const [status, setStatus] = useState<OrdersStatus | null>(null);
  const [blotter, setBlotter] = useState<Blotter | null>(null);
  const [blotterErr, setBlotterErr] = useState<string | null>(null);
  const [ledger, setLedger] = useState<LedgerView | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewAt, setPreviewAt] = useState(0);
  const [typed, setTyped] = useState("");
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(0);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [edit, setEdit] = useState<null | "mandate" | "live" | "import">(null);
  const [editText, setEditText] = useState("");
  const symbolRef = useRef<HTMLInputElement>(null);
  const latest = useRef({ draft, status, blotter, preview, typed, sel, busy, edit });
  latest.current = { draft, status, blotter, preview, typed, sel, busy, edit };

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await ordersApi.status());
    } catch (e) {
      setMsg({ text: `ERR: ORDER STATUS UNAVAILABLE (${(e as ApiError).message})`, cls: "err" });
    }
  }, []);
  const loadLedger = useCallback(async () => {
    try {
      setLedger(await ordersApi.ledger());
    } catch {
      setLedger(null);
    }
  }, []);
  const loadBlotter = useCallback(async (broker: OrderBroker) => {
    try {
      setBlotter(await ordersApi.blotter(broker));
      setBlotterErr(null);
    } catch (e) {
      setBlotter(null);
      setBlotterErr((e as ApiError).message);
    }
  }, []);
  const reload = useCallback(async () => {
    await Promise.all([loadStatus(), loadLedger(), loadBlotter(latest.current.draft.broker)]);
    setNow(Date.now() / 1000);
  }, [loadStatus, loadLedger, loadBlotter]);

  useEffect(() => {
    void reload();
  }, [reload, draft.broker]);
  usePanelRefresh(panelId, () => void reload());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);

  // The one-time token is short lived: when it runs out the review is dropped, never kept on screen as if it still worked.
  const left = preview?.token && preview.token_ttl_s ? Math.max(0, Math.ceil(previewAt + preview.token_ttl_s - now)) : null;
  useEffect(() => {
    if (preview?.token && left === 0) {
      setPreview(null);
      setTyped("");
      setMsg({ text: "THE CONFIRM TOKEN EXPIRED: REVIEW THE ORDER AGAIN", cls: "warn" });
    }
  }, [left, preview]);

  const change = (patch: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setPreview(null); // any change voids the review: the token was issued for exactly the old order
    setTyped("");
  };

  const review = useCallback(async () => {
    const { draft: d, busy: b } = latest.current;
    if (b) return;
    const body = toBody(d);
    if ("error" in body) return setMsg({ text: body.error, cls: "warn" });
    setBusy(true);
    setMsg(null);
    try {
      const p = await ordersApi.preview(body);
      setPreview(p);
      setPreviewAt(Date.now() / 1000);
      setTyped("");
      if (!p.token) setMsg({ text: "THE MANDATE REFUSES THIS ORDER: NOTHING CAN BE SENT", cls: "err" });
    } catch (e) {
      setPreview(null);
      setMsg({ text: `${(e as ApiError).message}`, cls: (e as ApiError).kind === "key_required" ? "warn" : "err" });
    }
    setBusy(false);
    void loadLedger();
  }, [loadLedger]);

  const send = useCallback(async () => {
    const { preview: p, typed: t, busy: b } = latest.current;
    if (b || !p?.token) return;
    if (!confirmReady(p.mode, p.order.symbol, t)) return setMsg({ text: `TYPE ${p.order.symbol} TO CONFIRM A LIVE ORDER`, cls: "warn" });
    const body = toBody({ ...latest.current.draft });
    if ("error" in body) return;
    setBusy(true);
    try {
      const r = await ordersApi.submit(body, p.token);
      setMsg({ text: `SENT ${p.mode.toUpperCase()} ORDER ${r.order.id ?? ""} ${r.order.status}`, cls: p.mode === "live" ? "warn" : "up" });
    } catch (e) {
      setMsg({ text: (e as ApiError).message, cls: "err" });
    }
    setPreview(null);
    setTyped("");
    setBusy(false);
    await reload();
  }, [reload]);

  const kill = useCallback(async () => {
    try {
      const r = await ordersApi.kill();
      const lines = Object.entries(r.brokers).map(([id, x]) => `${id.toUpperCase()}: ${x.detail}`);
      setMsg({ text: `KILL SWITCH ON. ${lines.join(" · ")}`, cls: "err" });
    } catch (e) {
      setMsg({ text: `KILL FAILED: ${(e as ApiError).message}. TRY AGAIN`, cls: "err" });
    }
    setPreview(null);
    await reload();
  }, [reload]);

  const unkill = useCallback(async () => {
    try {
      await ordersApi.unkill();
      setMsg({ text: "KILL SWITCH RELEASED: ORDERS ARE ALLOWED AGAIN", cls: "warn" });
    } catch (e) {
      setMsg({ text: (e as ApiError).message, cls: "err" });
    }
    await reload();
  }, [reload]);

  const cancelSelected = useCallback(async () => {
    const { blotter: bl, sel: i, draft: d } = latest.current;
    const o = bl?.open_orders?.[i];
    if (!o?.id) return setMsg({ text: "NO OPEN ORDER SELECTED", cls: "warn" });
    try {
      await ordersApi.cancel(d.broker, o.id);
      setMsg({ text: `CANCEL SENT FOR ${o.id}`, cls: "dim" });
    } catch (e) {
      setMsg({ text: (e as ApiError).message, cls: "err" });
    }
    await reload();
  }, [reload]);

  const commitEdit = useCallback(async () => {
    const { edit: kind, status: st, draft: d } = latest.current;
    try {
      if (kind === "live") {
        const on = !st?.live_enabled;
        await ordersApi.setLive(on, on ? editText : undefined);
        setMsg({ text: on ? "LIVE ORDERS ARE ON: REAL MONEY" : "LIVE ORDERS ARE OFF", cls: on ? "warn" : "up" });
      } else if (kind === "mandate" && st) {
        const m = parseMandate(editText, st.mandate);
        if ("error" in m) return setMsg({ text: m.error, cls: "warn" });
        await ordersApi.setMandate(m);
        setMsg({ text: "MANDATE SAVED (ANY OPEN REVIEW IS VOID)", cls: "up" });
        setPreview(null);
      } else if (kind === "import") {
        const r = await ordersApi.importFills(d.broker, editText.trim());
        setMsg({ text: r.detail, cls: "up" });
        void refreshPortfolios();
      }
      setEdit(null);
    } catch (e) {
      setMsg({ text: (e as ApiError).message, cls: "err" });
    }
    await reload();
  }, [editText, reload]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { preview: p, status: st, blotter: bl } = latest.current;
        switch (e.key) {
          case "e":
            symbolRef.current?.focus();
            return true;
          case "b":
            change({ broker: cycle(BROKER_ORDER, latest.current.draft.broker) });
            return true;
          case "s":
            change({ side: latest.current.draft.side === "buy" ? "sell" : "buy" });
            return true;
          case "t":
            change({ type: cycle(TYPES, latest.current.draft.type) });
            return true;
          case "g":
            change({ tif: cycle(TIFS, latest.current.draft.tif) });
            return true;
          case "Enter":
            void review();
            return true;
          case "y":
            if (p?.mode === "paper") void send();
            else if (p) setMsg({ text: `A LIVE ORDER IS CONFIRMED BY TYPING ${p.order.symbol} IN THE BOX BELOW THE REVIEW`, cls: "warn" });
            return true;
          case "Escape":
            if (latest.current.edit) setEdit(null);
            else setPreview(null);
            return true;
          case "x":
            void kill();
            return true;
          case "u":
            void unkill();
            return true;
          case "l":
            setEdit("live");
            setEditText("");
            return true;
          case "m":
            if (st) {
              setEdit("mandate");
              setEditText(mandateText(st.mandate));
            }
            return true;
          case "i":
            setEdit("import");
            setEditText(SLOT_MODE[latest.current.draft.broker] === "paper" ? "PAPER" : latest.current.draft.broker === "kite" ? "KITE" : "ALPACA");
            return true;
          case "c":
            void cancelSelected();
            return true;
          case "ArrowDown":
            setSel((i) => Math.min(i + 1, Math.max(0, (bl?.open_orders?.length ?? 1) - 1)));
            return true;
          case "ArrowUp":
            setSel((i) => Math.max(0, i - 1));
            return true;
          case "r":
            void reload();
            return true;
        }
        return false;
      }),
    [panelId, review, send, kill, unkill, cancelSelected, reload],
  );

  if ("error" in parsed)
    return (
      <div className="fn">
        <div className="line err">{parsed.error}</div>
        <div className="line dim">{ORD_USAGE}</div>
      </div>
    );

  const slotMode = SLOT_MODE[draft.broker];
  const mode = preview?.mode ?? slotMode;
  const live = mode === "live";
  const row = status?.brokers.find((b) => b.id === draft.broker);
  const keyDown = (ev: React.KeyboardEvent, onEnter: () => void) => {
    if (!ev.ctrlKey && !ev.altKey && !ev.metaKey) ev.stopPropagation(); // plain keys stay in the field; chords (Ctrl+K) still reach the command line
    if (ev.key === "Enter") onEnter();
    else if (ev.key === "Escape") (ev.target as HTMLElement).blur();
  };

  return (
    <div className="fn ord" data-testid="ord-panel">
      <div className="line">
        <span className="acc">ORD</span> ORDER TICKET <span className="dim legend">· E EDIT · B BROKER · S SIDE · T TYPE · ENTER REVIEW · X KILL · U RELEASE · L LIVE · M MANDATE · C CANCEL · I FILLS TO PORT</span>
      </div>
      <div className={live ? "ord-banner ord-live" : "ord-banner ord-paper"} data-testid="ord-banner" data-mode={mode}>
        {live ? `LIVE · REAL MONEY · ${BROKER_NAME[draft.broker]}` : `PAPER · PLAY MONEY · ${BROKER_NAME[draft.broker]}`}
      </div>
      {draft.broker === "kite" && <div className="warn">KITE HAS NO PAPER MODE: EVERY KITE ORDER IS REAL MONEY</div>}
      {msg && (
        <div className={msg.cls} data-testid="ord-msg">
          {msg.text}
        </div>
      )}
      {status?.kill.on && (
        <div className="err" data-testid="ord-kill-on">
          KILL SWITCH IS ON: NO ORDER CAN BE SENT. PRESS U TO RELEASE
        </div>
      )}
      {status && (
        <div className="dim">
          LIVE ORDERS {status.live_enabled ? <span className="err">ON</span> : "OFF"} · TRADES TODAY {status.trades_today} OF {status.mandate.max_trades_per_day} · MANDATE {status.mandate.symbols.length ? status.mandate.symbols.join(",") : "NO SYMBOLS ALLOWED"} · MAX {status.mandate.max_shares} SHARES / {money(status.mandate.max_notional)} PER ORDER / {money(status.mandate.max_gross)} GROSS
        </div>
      )}
      {row && !row.ready && <div className="warn">{row.message}</div>}

      <div className="ord-ticket" data-testid="ord-ticket">
        <select className="ord-in" aria-label="broker" value={draft.broker} onChange={(e) => change({ broker: e.target.value as OrderBroker })} onKeyDown={(e) => e.stopPropagation()}>
          {BROKER_ORDER.map((b) => (
            <option key={b} value={b}>
              {BROKER_NAME[b]}
            </option>
          ))}
        </select>
        <select className="ord-in" aria-label="side" value={draft.side} onChange={(e) => change({ side: e.target.value as Draft["side"] })} onKeyDown={(e) => e.stopPropagation()}>
          <option value="buy">BUY</option>
          <option value="sell">SELL</option>
        </select>
        <input ref={symbolRef} className="ord-in" aria-label="symbol" placeholder="SYMBOL" size={10} value={draft.symbol} onChange={(e) => change({ symbol: e.target.value.toUpperCase() })} onKeyDown={(e) => keyDown(e, () => void review())} />
        <input className="ord-in" aria-label="quantity" placeholder="QTY" size={7} value={draft.qty} onChange={(e) => change({ qty: e.target.value })} onKeyDown={(e) => keyDown(e, () => void review())} />
        <select className="ord-in" aria-label="order type" value={draft.type} onChange={(e) => change({ type: e.target.value as Draft["type"] })} onKeyDown={(e) => e.stopPropagation()}>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t.toUpperCase()}
            </option>
          ))}
        </select>
        <input className="ord-in" aria-label="price" placeholder={draft.type === "market" ? "MARKET" : draft.type === "limit" ? "LIMIT PRICE" : "STOP PRICE"} size={11} disabled={draft.type === "market"} value={draft.price} onChange={(e) => change({ price: e.target.value })} onKeyDown={(e) => keyDown(e, () => void review())} />
        <select className="ord-in" aria-label="time in force" value={draft.tif} onChange={(e) => change({ tif: e.target.value as Draft["tif"] })} onKeyDown={(e) => e.stopPropagation()}>
          {TIFS.map((t) => (
            <option key={t} value={t}>
              {t.toUpperCase()}
            </option>
          ))}
        </select>
        <button className="ord-btn" disabled={busy} onClick={() => void review()}>
          REVIEW
        </button>
      </div>

      {preview && (
        <div className={live ? "ord-review ord-live-box" : "ord-review"} data-testid="ord-review">
          <div>
            STEP 2 OF 2 · <b>{preview.line}</b> · {preview.mode.toUpperCase()} · ACCOUNT …{preview.account.id.slice(-4)} · {preview.price !== null ? `REF PRICE ${preview.price} (${preview.price_note})` : "NO PRICE"}
          </div>
          {preview.account.note && <div className={preview.mode === "live" ? "err" : "dim"}>{preview.account.note}</div>}
          {preview.check.checks.map((c) => (
            <div key={c.name} className={c.ok ? "up" : "err"}>
              {c.ok ? "PASS" : "FAIL"} {c.name}: {c.detail}
            </div>
          ))}
          {preview.token ? (
            <div>
              {preview.mode === "paper" ? (
                <span>
                  PRESS <b>Y</b> TO SEND THE PAPER ORDER{" "}
                  <button className="ord-btn" disabled={busy} onClick={() => void send()}>
                    SEND PAPER ORDER
                  </button>
                </span>
              ) : (
                <span>
                  REAL MONEY. TYPE <b>{confirmWord(preview.mode, preview.order.symbol)}</b> THEN ENTER:{" "}
                  <input className="ord-in" aria-label="confirm live order" autoFocus size={12} value={typed} onChange={(e) => setTyped(e.target.value.toUpperCase())} onKeyDown={(e) => keyDown(e, () => void send())} />
                  <button className="ord-btn ord-btn-live" disabled={busy || !confirmReady(preview.mode, preview.order.symbol, typed)} onClick={() => void send()}>
                    SEND LIVE ORDER
                  </button>
                </span>
              )}
              <span className="dim"> · TOKEN GOOD ONCE, {left}S LEFT · ESC DROPS THIS REVIEW</span>
            </div>
          ) : (
            <div className="err">NO CONFIRM TOKEN: THE MANDATE (M) OR THE ACCOUNT REFUSES THIS ORDER</div>
          )}
        </div>
      )}

      {edit && (
        <div className="ord-edit" data-testid="ord-edit">
          {edit === "live" && (status?.live_enabled ? <span className="err">LIVE ORDERS ARE ON. ENTER SWITCHES THEM OFF</span> : <span>TYPE EXACTLY: <b>{LIVE_PHRASE}</b></span>)}
          {edit === "mandate" && <span>MANDATE (SYMBOLS, THEN SHARES= NOTIONAL= GROSS= TRADES=): </span>}
          {edit === "import" && <span>ADD TODAY&apos;S FILLS TO PORTFOLIO (PAPER FILLS GO TO A PAPER PORTFOLIO): </span>}
          <input className="ord-in" aria-label="ord edit" autoFocus size={edit === "mandate" ? 60 : 44} value={editText} onChange={(e) => setEditText(e.target.value)} onKeyDown={(ev) => { keyDown(ev, () => void commitEdit()); if (ev.key === "Escape") setEdit(null); }} />
        </div>
      )}

      <div className="acc ord-h">BLOTTER · {BROKER_NAME[draft.broker]}</div>
      {blotterErr && <div className="warn">{blotterErr}</div>}
      {blotter && (
        <>
          <div className="dim">
            ACCOUNT …{blotter.account.id.slice(-4)} · {blotter.account.mode.toUpperCase()} · EQUITY {money(blotter.account.equity, blotter.account.currency)} · CASH {money(blotter.account.cash)} · BUYING POWER {money(blotter.account.buying_power)} · AS OF {ageText(blotter.as_of, now)}
          </div>
          {Object.entries(blotter.errors).map(([k, v]) => (
            <div key={k} className="err">
              ERR {k.toUpperCase()}: {v}
            </div>
          ))}
          <div className="dim">OPEN ORDERS</div>
          {blotter.open_orders?.length === 0 && <div className="dim">NONE</div>}
          {blotter.open_orders?.map((o, i) => (
            <div key={o.id ?? i} className={i === sel ? "ord-sel" : ""} data-testid="ord-open">
              {o.side.toUpperCase()} {o.qty} {o.symbol} {o.type?.toUpperCase()} {o.limit_price ?? o.stop_price ?? ""} {o.tif?.toUpperCase()} · {o.status} · {o.id}
            </div>
          ))}
          <div className="dim">FILLS TODAY</div>
          {blotter.fills?.length === 0 && <div className="dim">NONE</div>}
          {blotter.fills?.map((f) => (
            <div key={f.fill_id}>
              {f.side.toUpperCase()} {f.qty} {f.symbol} @ {f.price} {f.currency} · ORDER {f.order_id}
            </div>
          ))}
          <div className="dim">POSITIONS</div>
          {blotter.positions?.length === 0 && <div className="dim">NONE</div>}
          {blotter.positions?.map((p) => (
            <div key={p.symbol}>
              {p.symbol} {p.qty} · AVG {money(p.avg_cost)} · LAST {money(p.price)} · VALUE {money(p.market_value)}
            </div>
          ))}
        </>
      )}

      <div className="acc ord-h">LEDGER {ledger && (ledger.verify.ok ? <span className="up">· CHAIN VERIFIED ({ledger.verify.count} ENTRIES)</span> : <span className="err">· CHAIN BROKEN AT {ledger.verify.broken_at}: {ledger.verify.reason}</span>)}</div>
      {ledger?.entries.length === 0 && <div className="dim">NO ORDER EVENTS YET</div>}
      {ledger?.entries.slice(0, 15).map((e) => (
        <div key={e.seq} className={e.event === "refused" || e.event === "failed" ? "err" : "dim"} data-testid="ord-ledger-row">
          #{e.seq} {ageText(e.at, now)} · {e.event.toUpperCase()} · {e.mode?.toUpperCase()} {e.order?.symbol ? `${(e.order.side ?? "").toUpperCase()} ${e.order.qty} ${e.order.symbol}` : ""} {e.reason ? `· ${e.reason}` : ""}
        </div>
      ))}
      <div className="dim">THE AI CANNOT PLACE, CHANGE OR CANCEL ORDERS. EVERY ORDER NEEDS YOUR CONFIRM. FILLS YOU ADD TO PORT ARE LABELLED PAPER / ALPACA / KITE-ORDERS AND NEVER REMOVED BY SYNC.</div>
    </div>
  );
}
