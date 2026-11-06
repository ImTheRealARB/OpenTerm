import { useEffect, useState } from "react";
import { btApi } from "../net/btApi";
import type { BtTemplate } from "../net/types";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";

/**
 * GUI mode only: the empty BT panel lists the starter strategies (GET /api/bt/templates) as plain-language buttons.
 * Pick one, check the stock, press "Run backtest". The run goes through the same POST /api/bt/run as a typed command
 * (BT passes `onRun`), so the result keeps its "HISTORICAL SIMULATION, NOT A FORECAST" label, source and costs.
 *
 * Terminal mode renders nothing here (its empty state is unchanged).
 */
export function BtStarter({ onRun }: { onRun: (code: string, symbol: string) => void }) {
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const [templates, setTemplates] = useState<BtTemplate[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [picked, setPicked] = useState<BtTemplate | null>(null);
  const [symbol, setSymbol] = useState("AAPL");

  useEffect(() => {
    if (!gui) return;
    let alive = true;
    btApi
      .templates()
      .then((r) => alive && setTemplates(r.templates))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [gui]);

  if (!gui) return null;
  if (failed) return <div className="dim">The starter strategies could not be loaded. Press F5 to retry.</div>;
  if (!templates) return <div className="dim">Loading starter strategies…</div>;

  return (
    <div className="bt-starter" data-testid="bt-starter">
      <div className="bt-starter-h">Pick a starter strategy</div>
      <div className="bt-starter-list" role="group" aria-label="Starter strategies">
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            className={"bt-template" + (picked?.id === t.id ? " on" : "")}
            data-testid="bt-template"
            aria-pressed={picked?.id === t.id}
            onClick={() => setPicked(t)}
          >
            {/* The summary is already plain English ("Buy when ..."); the upper-case title is the technical name. */}
            {t.summary} <span className="dim">{t.title}</span>
          </button>
        ))}
      </div>
      <div className="bt-starter-run">
        <label>
          Stock{" "}
          <input
            className="bt-starter-sym"
            value={symbol}
            spellCheck={false}
            autoComplete="off"
            aria-label="Stock to test"
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (!e.ctrlKey && !e.altKey && !e.metaKey) e.stopPropagation(); // typing here must not trigger panel keys; chords still bubble
            }}
          />
        </label>
        <button type="button" disabled={!picked || !symbol.trim()} onClick={() => picked && onRun(picked.code, symbol.trim())}>
          Run backtest
        </button>
        <span className="dim"> 5 years of daily prices, default fees. Past results do not predict the future.</span>
      </div>
    </div>
  );
}
