import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { execute } from "../command/execute";
import { info } from "../command/status";
import { runItem } from "../components/windowMenuRun";
import type { OptionAction } from "../components/windowMenu";
import { effectiveBindings } from "../keys/keys";
import { dispatchPanelKey } from "../keys/panelKeys";
import { CHART_TYPES, CHART_TYPE_LABELS, type ChartType } from "../chart/chartTypes";
import { INTERVAL_CHOICES, intervalFits, intervalToken, limitText, parseGpArgs, withChartType, withInterval } from "../functions/gpArgs";
import { useHistoryLimits } from "../functions/useHistoryLimits";
import { settingsStore } from "../settings/runtime";
import { focusPanel, replaceView, workspace } from "../state/workspace";
import { useStore } from "../state/store";
import { onAskRequest } from "./askBus";
import { chromeKeyDown, focusCommandLine } from "./chrome";
import { openHelp } from "./helpState";
import { runCommand } from "./run";
import { useTabsOn } from "./tabsState";
import { askButton, askCommands, buttonsFor, keyHint, keyInit, type ToolbarButton } from "./toolbars";

/**
 * GUI-only button row under a panel's title bar.
 *
 * Left: buttons for this function (`toolbars.ts`), each of which "presses" a key the panel already handles.
 * Right: the same five buttons on every panel: "?" (help drawer), CSV, Refresh, Max/Restore, Close. Those reuse
 * `runItem` from the window-frame menu (components/windowMenuRun.ts), so they do exactly what OPTIONS does.
 *
 * Keyboard: every button is a real <button>, so Tab reaches it and Enter / Space press it. Plain keys typed while a
 * toolbar button has focus must not ALSO reach the panel's key handler (Enter would fire twice), hence `chromeKeyDown`.
 */
export function PanelToolbar({ id, fn, args, symbol }: { id: number; fn: string | undefined; args: readonly string[]; symbol?: string }) {
  const maximized = useStore(workspace, (s) => s.maximized === id);
  const tabs = useTabsOn(); // PanelToolbar only renders in GUI mode, so this alone means "GUI tabs layout"
  // The button whose inline prompt is open (WL "Add" asks for symbols), or null.
  const [ask, setAsk] = useState<ToolbarButton | null>(null);
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const buttons = buttonsFor(fn, args).filter((b) => !b.bandHidden); // bandHidden ones live in the help drawer only
  // GP: the range that is on now, so its button shows as the active choice (blue fill). Empty for every other function.
  const activeRange = fn === "GP" ? parseGpArgs([...args], settingsStore.get().chart).range.toUpperCase() : "";
  // Only the GP candle-length dropdown uses this; other panels pass no symbol to fetch for.
  const limits = useHistoryLimits(fn === "GP" ? symbol : undefined);

  // Fit to one row. A narrow panel (half of a 1440 px screen) cannot show every button, and a wrapped band pushes the
  // panel body down. So the band compacts in steps until it fits:
  //   level 1: hide ? / CSV / Refresh / Max / Close (the title bar's OPTIONS menu has all five);
  //   level 2 (GP only): the eight range buttons become one dropdown.
  // Each width / content change starts again from level 0. The check runs in a layout effect, before the browser
  // paints, so a too-wide level is never seen.
  const band = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = band.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ask]);
  const fitKey = `${width}|${fn}|${args.join(" ")}|${tabs}|${maximized}`;
  const [fit, setFit] = useState({ key: "", level: 0 });
  const level = fit.key === fitKey ? fit.level : 0;
  const maxLevel = fn === "GP" ? 2 : 1;
  useLayoutEffect(() => {
    const el = band.current;
    if (el && level < maxLevel && wraps(el)) setFit({ key: fitKey, level: level + 1 });
  }, [fitKey, level, maxLevel]);
  const isRangeButton = (b: ToolbarButton) => fn === "GP" && b.key >= "1" && b.key <= "8" && b.label.length <= 3;
  const ranges = buttons.filter(isRangeButton);

  // A panel's empty state ("Add a stock") can open one of our ask boxes (see askBus.ts).
  useEffect(
    () =>
      onAskRequest((r) => {
        if (r.panelId !== id) return;
        const b = askButton(fn, r.label);
        if (!b) return;
        setText("");
        setAsk(b);
        setTimeout(() => input.current?.focus(), 0);
      }),
    [id, fn],
  );

  /** After a MOUSE click let go of the button so the panel's own keys (j/k, Enter...) work right away; keep keyboard focus for Tab users. */
  const afterClick = (e: MouseEvent<HTMLElement>) => {
    if (e.detail > 0) e.currentTarget.blur();
  };

  const press = (b: ToolbarButton, e: MouseEvent<HTMLElement>) => {
    if (b.ask) {
      setText("");
      setAsk(b);
      // The input mounts on the next render; focus it then.
      setTimeout(() => input.current?.focus(), 0);
      return;
    }
    if (b.open) {
      focusPanel(id);
      execute(b.open, { newPanel: true });
      afterClick(e);
      return;
    }
    focusPanel(id);
    // Same KeyboardEvent the browser would send for that key; the panel's handler returns false when it has no use for it
    // (a key that needs a loaded chart, a different view of the panel ...).
    if (!dispatchPanelKey(id, new KeyboardEvent("keydown", keyInit(b)))) info(`${b.label.toUpperCase()}: NOT AVAILABLE IN THIS VIEW OR WHILE IT LOADS`);
    afterClick(e);
  };

  const option = (action: OptionAction, label: string, e: MouseEvent<HTMLElement>) => {
    runItem(id, { kind: "action", action, label });
    afterClick(e);
  };

  const submitAsk = () => {
    if (!ask?.ask || text.trim() === "") return;
    focusPanel(id);
    // Runs the equivalent command line text, e.g. "WL TECH ADD AAPL MSFT" (one command per comma-separated entry for
    // the portfolio box). A failure keeps the prompt open so the text can be fixed.
    const cmds = askCommands(ask.ask, args, text, symbol);
    if (cmds.length > 0 && cmds.every((c) => runCommand(c))) setAsk(null);
  };

  if (ask?.ask) {
    return (
      <div className="pt" role="toolbar" aria-label={`Panel ${id}: ${ask.label}`} onKeyDown={chromeKeyDown}>
        <span className="pt-ask-l">{ask.label.toUpperCase()}</span>
        <input
          ref={input}
          className="pt-ask"
          data-testid="pt-ask"
          type="text"
          value={text}
          spellCheck={false}
          autoComplete="off"
          placeholder={ask.ask.prompt}
          aria-label={ask.ask.prompt}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.ctrlKey || e.altKey || e.metaKey) return; // chords bubble (Ctrl+K must still reach the command line)
            if (e.key === "Enter") {
              e.preventDefault();
              submitAsk();
            } else if (e.key === "Escape") {
              setAsk(null); // chromeKeyDown (on the row) then puts focus back on the command line
            }
          }}
        />
        <button type="button" className="pt-b" onClick={submitAsk}>
          Run
        </button>
        <button type="button" className="pt-b" onClick={() => { setAsk(null); focusCommandLine(); }}>
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div ref={band} className="pt" role="toolbar" aria-label={`Panel ${id} buttons`} data-testid={`pt-${id}`} data-fit={level} onKeyDown={chromeKeyDown}>
      {level >= 2 && ranges.length > 0 && (
        // Compact GP band: the range buttons as one dropdown. Choosing one presses the same panel key the button would.
        <select
          className="pt-b pt-sel"
          data-testid="gp-range"
          title="Time range"
          aria-label="Time range"
          value={ranges.some((b) => b.label === activeRange) ? activeRange : ""}
          onChange={(e) => {
            const b = ranges.find((r) => r.label === e.target.value);
            e.currentTarget.blur();
            if (!b) return;
            focusPanel(id);
            dispatchPanelKey(id, new KeyboardEvent("keydown", keyInit(b)));
          }}
        >
          {!ranges.some((b) => b.label === activeRange) && <option value="">Range</option>}
          {ranges.map((b) => (
            <option key={b.label} value={b.label}>
              {b.label}
            </option>
          ))}
        </select>
      )}
      {buttons.map((b) => {
        const hint = keyHint(b);
        // The range buttons (1D ... MAX) are choices: the one that is on is marked, and says so to screen readers.
        const isRange = isRangeButton(b);
        if (isRange && level >= 2) return null; // shown as the dropdown above
        const on = isRange && b.label === activeRange;
        return (
          <button key={b.label} type="button" className={"pt-b pt-fn" + (on ? " on" : "")} aria-pressed={isRange ? on : undefined} title={b.title ?? b.label} onClick={(e) => press(b, e)}>
            {hint && <span className="pt-k" aria-hidden="true">{hint}) </span>}
            {b.label}
          </button>
        );
      })}
      {fn === "GP" && (
        // Chart type (candles, line, ...). Same path as typing "GP LINE"; the C key still cycles through them.
        <select
          className="pt-b pt-sel"
          data-testid="gp-type"
          title="Chart type"
          aria-label="Chart type"
          value={parseGpArgs([...args], settingsStore.get().chart).type}
          onChange={(e) => {
            const v = e.target.value as ChartType;
            const d = settingsStore.get().chart;
            replaceView(id, (view) => ({ ...view, args: withChartType(view.args, v, d) }));
            e.currentTarget.blur();
          }}
        >
          {CHART_TYPES.map((t) => (
            <option key={t} value={t}>
              {CHART_TYPE_LABELS[t]}
            </option>
          ))}
        </select>
      )}
      {fn === "GP" && (
        // Candle length. Changing it rewrites the panel's args (same path as typing "GP 5D 15MIN"); the range buttons keep it.
        <select
          className="pt-b pt-sel"
          data-testid="gp-interval"
          title="Candle length (Auto = chosen by the range). Minute candles only reach back days or weeks."
          aria-label="Candle length"
          value={INTERVAL_CHOICES.some(([, t]) => t === parseGpArgs([...args]).interval) ? parseGpArgs([...args]).interval : ""}
          onChange={(e) => {
            const v = e.target.value;
            const d = settingsStore.get().chart;
            replaceView(id, (view) => ({ ...view, args: withInterval(view.args, v, d) }));
            e.currentTarget.blur();
          }}
        >
          {INTERVAL_CHOICES.map(([label, token]) => {
            // Minute candles only reach back so far, and how far depends on which source answers for this symbol (the backend
            // reports it): say how far, and grey out what the current range cannot use.
            const days = token ? limits?.[intervalToken(token)] : undefined;
            const fits = !token || intervalFits(parseGpArgs([...args]).range, token, limits);
            return (
              <option key={label} value={token} disabled={!fits}>
                {days !== undefined ? `${label} (${limitText(days)})` : label}
              </option>
            );
          })}
        </select>
      )}
      <span className="pt-sp" />
      {level < 1 && (<>
      <button type="button" className="pt-b pt-help" title={`Help for this panel (${effectiveBindings().helpDrawer[0] ?? "no key bound"})`} aria-label="Help for this panel" onClick={(e) => { openHelp(id, e.currentTarget); }}>
        ?
      </button>
      <button type="button" className="pt-b" title="Export the table as CSV (Alt+X)" onClick={(e) => option("exportCsv", "EXPORT CSV", e)}>
        CSV
      </button>
      <button type="button" className="pt-b" title="Reload the panel's data (F5)" onClick={(e) => option("refresh", "REFRESH", e)}>
        Refresh
      </button>
      {/* In tabs mode every panel already fills the workspace, so Max would do nothing visible. */}
      {!tabs && (
        <button type="button" className="pt-b" title="Maximize or restore this panel (Ctrl+Shift+F)" onClick={(e) => option("maximize", "MAXIMIZE / RESTORE", e)}>
          {maximized ? "Restore" : "Max"}
        </button>
      )}
      <button type="button" className="pt-b pt-close" title="Close this panel (Alt+W)" aria-label="Close this panel" onClick={(e) => option("closePanel", "CLOSE PANEL", e)}>
        Close
      </button>
      </>)}
    </div>
  );
}

/** True when the band's last item sits on a lower line than its first: the row has wrapped. */
function wraps(el: HTMLElement): boolean {
  const first = el.firstElementChild as HTMLElement | null;
  const last = el.lastElementChild as HTMLElement | null;
  return !!first && !!last && last.offsetTop > first.offsetTop + 2;
}
