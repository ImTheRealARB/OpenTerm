/**
 * Phase 24: GP bar replay (`GP AAPL REPLAY 2024-03-01`). Owns the replay clock, the keys and the replay paper book; GP hands
 * the chart `shown` instead of the full bars, so nothing on the chart can see a hidden bar (see `chart/replay.ts`).
 *
 * Keys while replaying (the panel's other keys keep working):
 *   .  next bar        ,  previous bar (only hides it again; trades already filled stay)
 *   Space play / pause     s  speed 1, 2, 5, 10 bars per second
 *   Shift+B buy   Shift+S sell   Shift+F flatten    (fill at the NEXT bar's open; practice only, nothing is sent)
 *   Shift+J save the session's trades to the journal (JRNL), named "REPLAY <SYMBOL> <date>"
 * Linked panels (LINK A..D) that are also replaying follow this panel's clock (Phase 22 link bus).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { BarData } from "../chart/chartBase";
import { onLink, publishLink } from "../chart/linkBus";
import { emptyBook, fillsCsv, firstReveal, onReveal, parseDay, queue, revealed, SPEEDS, type Book } from "../chart/replay";
import { info, fail } from "../command/status";
import { registerPanelKeys } from "../keys/panelKeys";
import { journalApi } from "../net/journalApi";
import { useLatest } from "../state/useLatest";

/** Units per key press in the replay book (a round lot for shares; for crypto it is 100 coins, so P&L reads per 100). */
export const REPLAY_QTY = 100;

export interface ReplayState {
  /** The bars the chart may show (all of them when not replaying). */
  shown: BarData | undefined;
  active: boolean;
  n: number;
  total: number;
  playing: boolean;
  speed: number;
  book: Book;
  last: number; // close of the last revealed bar
}

export function useReplay(panelId: number, bars: BarData | undefined, spec: { start: string | null } | undefined, linkGroup: string | undefined, symbol: string): ReplayState {
  const [n, setN] = useState(0);
  const [book, setBook] = useState<Book>(emptyBook);
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(0);
  const active = !!spec && !!bars && bars.t.length > 1;

  // A new load or a new start day: start again (hidden bars, empty book).
  const startKey = `${spec?.start ?? ""}:${bars?.t.length ?? 0}:${bars?.t[0] ?? 0}`;
  useEffect(() => {
    if (!spec || !bars) return;
    const day = spec.start ? parseDay(spec.start) : null;
    setN(day !== null ? firstReveal(bars.t, day) : Math.max(1, bars.t.length - 100));
    setBook(emptyBook());
    setPlaying(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `startKey` stands for the bars and the start day
  }, [startKey, !!spec]);

  const latest = useLatest({ n, book, bars, active, playing, linkGroup });

  /** Move the clock to `to` revealed bars; each newly revealed bar fills the pending orders at its open. */
  const moveTo = (to: number, broadcast = true) => {
    const { n: cur, bars: b, linkGroup: g } = latest.current;
    if (!b) return;
    const k = Math.max(1, Math.min(b.t.length, to));
    if (k > cur) setBook((bk) => {
      let out = bk;
      for (let i = cur; i < k; i++) out = onReveal(out, b, i);
      return out;
    });
    setN(k);
    if (k >= b.t.length) setPlaying(false);
    if (broadcast && g) publishLink({ group: g, from: panelId, kind: "replay", t: b.t[k - 1] });
  };
  const move = useRef(moveTo);
  move.current = moveTo;

  // Play: one bar every 1/speed seconds.
  useEffect(() => {
    if (!playing || !active) return;
    const id = setInterval(() => move.current(latest.current.n + 1), 1000 / SPEEDS[speedIdx]);
    return () => clearInterval(id);
  }, [playing, speedIdx, active, latest]);

  // Follow the group's replay clock (only while this panel replays too).
  useEffect(
    () =>
      onLink((m) => {
        const { active: on, bars: b, linkGroup: g } = latest.current;
        if (m.kind !== "replay" || !on || !b || m.group !== g || m.from === panelId) return;
        move.current(firstReveal(b.t, m.t + 1), false);
      }),
    [panelId, latest],
  );

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { active: on, n: cur, book: bk, bars: b } = latest.current;
        if (!on || !b) return false;
        switch (e.key) {
          case ".":
            move.current(cur + 1);
            return true;
          case ",":
            move.current(cur - 1);
            return true;
          case " ":
            setPlaying((x) => !x);
            return true;
          case "s":
            setSpeedIdx((i) => (i + 1) % SPEEDS.length);
            return true;
          case "B":
            setBook((x) => queue(x, "BUY", REPLAY_QTY));
            return true;
          case "S":
            setBook((x) => queue(x, "SELL", REPLAY_QTY));
            return true;
          case "F":
            setBook((x) => queue(x, "FLAT", 0));
            return true;
          case "J": {
            if (!bk.fills.length) {
              fail("REPLAY: NO TRADES TO SAVE");
              return true;
            }
            const name = `REPLAY ${symbol} ${new Date(b.t[0] * 1000).toISOString().slice(0, 10)}`;
            const mapping = { time: "time", symbol: "symbol", side: "side", qty: "qty", price: "price" };
            journalApi
              .importFile({ text: fillsCsv(symbol, bk.fills), broker: "generic", mapping, name })
              .then(() => info(`SAVED ${bk.fills.length} REPLAY FILLS TO JRNL AS "${name}"`))
              .catch((err: Error) => fail(`JRNL SAVE FAILED: ${err.message}`));
            return true;
          }
        }
        return false;
      }),
    [panelId, latest, symbol],
  );

  const shown = useMemo(() => (active && bars ? revealed(bars, n) : bars), [active, bars, n]);
  return {
    shown, active, n, total: bars?.t.length ?? 0, playing, speed: SPEEDS[speedIdx], book,
    last: shown && shown.c.length ? shown.c[shown.c.length - 1] : NaN,
  };
}
