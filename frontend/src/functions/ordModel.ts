/** Pure logic of the ORD panel: command words, the ticket draft, the mandate text. No React, no network. */
import type { Mandate, OrderBody, OrderBroker, OrderMode } from "../net/ordersApi";

export const ORD_USAGE = "USAGE: ORD [PAPER|ALPACA|KITE] [BUY|SELL] [QTY] [SYMBOL] [LMT PRICE | STP PRICE] [DAY|GTC|IOC]   e.g. ORD AAPL BUY 10 LMT 190.5";

/** PAPER is the default. ALPACA is the LIVE Alpaca account and KITE is always live (Kite has no paper mode). */
export const BROKER_WORDS: Record<string, OrderBroker> = { PAPER: "alpaca-paper", ALPACA: "alpaca-live", KITE: "kite" };
export const BROKER_ORDER: OrderBroker[] = ["alpaca-paper", "alpaca-live", "kite"];
export const BROKER_NAME: Record<OrderBroker, string> = { "alpaca-paper": "ALPACA PAPER", "alpaca-live": "ALPACA LIVE", kite: "ZERODHA KITE" };
/** What each slot is, for the loud banner. Mirrors the server's slot table only for display; the server decides what is real. */
export const SLOT_MODE: Record<OrderBroker, OrderMode> = { "alpaca-paper": "paper", "alpaca-live": "live", kite: "live" };

export interface Draft {
  broker: OrderBroker;
  symbol: string;
  side: "buy" | "sell";
  qty: string;
  type: "market" | "limit" | "stop";
  price: string;
  tif: "day" | "gtc" | "ioc";
}

export const EMPTY_DRAFT: Draft = { broker: "alpaca-paper", symbol: "", side: "buy", qty: "", type: "market", price: "", tif: "day" };

const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.\-&]{0,19}$/; // the same shape the server accepts (orders/model.py)

export function parseOrdArgs(args: string[]): Draft | { error: string } {
  const d: Draft = { ...EMPTY_DRAFT };
  const words = args.map((a) => a.toUpperCase());
  let sawSymbol = false;
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (w in BROKER_WORDS) d.broker = BROKER_WORDS[w];
    else if (w === "BUY" || w === "SELL") d.side = w.toLowerCase() as Draft["side"];
    else if (w === "DAY" || w === "GTC" || w === "IOC") d.tif = w.toLowerCase() as Draft["tif"];
    else if (w === "LMT" || w === "LIMIT" || w === "STP" || w === "STOP") {
      const px = words[i + 1];
      if (px === undefined || !/^\d*\.?\d+$/.test(px)) return { error: `${w} NEEDS A PRICE` };
      d.type = w.startsWith("L") ? "limit" : "stop";
      d.price = px;
      i++;
    } else if (/^\d*\.?\d+$/.test(w) && d.qty === "") d.qty = w;
    else if (!sawSymbol && SYMBOL_RE.test(w)) {
      d.symbol = w;
      sawSymbol = true;
    } else return { error: `${w.slice(0, 24)}: NOT AN ORDER WORD` };
  }
  return d;
}

/** The order body for the server, or the reason the draft is not one yet. Never carries a mode: the broker slot decides it. */
export function toBody(d: Draft): OrderBody | { error: string } {
  const symbol = d.symbol.trim().toUpperCase();
  if (!SYMBOL_RE.test(symbol)) return { error: "ENTER A SYMBOL" };
  const qty = Number(d.qty);
  if (d.qty.trim() === "" || !Number.isFinite(qty) || qty <= 0) return { error: "QTY MUST BE A POSITIVE NUMBER" };
  const body: OrderBody = { broker: d.broker, symbol, side: d.side, qty, type: d.type, tif: d.tif };
  if (d.type !== "market") {
    const px = Number(d.price);
    if (d.price.trim() === "" || !Number.isFinite(px) || px <= 0) return { error: `A ${d.type.toUpperCase()} ORDER NEEDS A PRICE` };
    if (d.type === "limit") body.limit_price = px;
    else body.stop_price = px;
  }
  return body;
}

/** Two-step confirm: for a live order the user must also type the symbol (so Enter cannot be held down into a real order). */
export function confirmWord(mode: OrderMode, symbol: string): string | null {
  return mode === "live" ? symbol.toUpperCase() : null;
}

export function confirmReady(mode: OrderMode, symbol: string, typed: string): boolean {
  const need = confirmWord(mode, symbol);
  return need === null || typed.trim().toUpperCase() === need;
}

// --- mandate as one line of text: "AAPL,MSFT SHARES=100 NOTIONAL=5000 GROSS=25000 TRADES=10" ---
export function mandateText(m: Mandate): string {
  return `${m.symbols.join(",")} SHARES=${m.max_shares} NOTIONAL=${m.max_notional} GROSS=${m.max_gross} TRADES=${m.max_trades_per_day}`.trim();
}

export function parseMandate(text: string, base: Mandate): Mandate | { error: string } {
  const out: Mandate = { ...base, symbols: [...base.symbols] };
  const keys: Record<string, keyof Mandate> = { SHARES: "max_shares", NOTIONAL: "max_notional", GROSS: "max_gross", TRADES: "max_trades_per_day" };
  for (const tok of text.trim().toUpperCase().split(/\s+/).filter(Boolean)) {
    const eq = tok.indexOf("=");
    if (eq < 0) {
      const syms = tok.split(",").filter(Boolean);
      if (!syms.every((s) => SYMBOL_RE.test(s))) return { error: `BAD SYMBOL LIST ${tok.slice(0, 40)}` };
      out.symbols = syms;
      continue;
    }
    const key = keys[tok.slice(0, eq)];
    const v = Number(tok.slice(eq + 1));
    if (!key || tok.slice(eq + 1) === "" || !Number.isFinite(v) || v < 0) return { error: `${tok.slice(0, 30)}: USE SHARES= NOTIONAL= GROSS= TRADES= WITH A NUMBER` };
    (out[key] as number) = key === "max_trades_per_day" ? Math.floor(v) : v;
  }
  return out;
}

export function money(x: number | null | undefined, ccy = ""): string {
  return x === null || x === undefined ? "-" : `${x.toLocaleString("en-US", { maximumFractionDigits: 2 })}${ccy ? " " + ccy : ""}`;
}

export function ageText(at: number, now: number): string {
  const s = Math.max(0, Math.round(now - at));
  return s < 60 ? "JUST NOW" : s < 3600 ? `${Math.floor(s / 60)}M AGO` : s < 86400 ? `${Math.floor(s / 3600)}H AGO` : `${Math.floor(s / 86400)}D AGO`;
}
