/**
 * SETTINGS: keyboard-editable settings and the shortcut editor. Changes apply at once, are mirrored to
 * localStorage and stored on the backend (`/api/settings`) by settings/sync.ts.
 */
import { ACTION_LABELS } from "../keys/actionLabels";
import { useEffect, useRef, useState } from "react";
import { info } from "../command/status";
import { prefillCommand } from "../components/CommandLine";
import { fmtPrice } from "../format";
import { KEYBINDINGS, chord, effectiveBindings, type Action } from "../keys/keys";
import { FIXED_ACTIONS, checkChord, diffBindings } from "../keys/overrides";
import { registerPanelKeys } from "../keys/panelKeys";
import { resetSettings, settingsStore, updateSettings } from "../settings/runtime";
import { AI_MODEL_CHOICES, AI_PROVIDERS, AI_VISION_CHOICES, CHART_RANGES, CHART_TYPES, DECIMALS, MODES, POLL_BOUNDS, STARTUPS, THOUSANDS, cycle, stepPoll, type PollKey, type Settings } from "../settings/schema";
import { cyclePreset, fontLabel } from "../settings/fontPresets";
import { THEMES, THEME_LABELS } from "../settings/themes";
import { useStore } from "../state/store";
import { listNav } from "./listNav";
import type { FunctionProps } from "./registry";

const SEP_LABEL: Record<string, string> = { ",": "COMMA", ".": "DOT", " ": "SPACE", "'": "APOSTROPHE", "": "NONE" };

interface SettingRow {
  kind: "setting";
  id: string;
  label: string;
  value: (s: Settings) => string;
  /** h/l or ←/→ (Enter / Space = forward). Absent: Enter runs `enter`. */
  change?: (s: Settings, dir: 1 | -1) => Settings;
  enter?: (s: Settings) => void;
}
interface KeyRow {
  kind: "key";
  action: Action;
}
type Row = SettingRow | KeyRow;

const poll = (k: PollKey, label: string): SettingRow => ({
  kind: "setting",
  id: `poll.${k}`,
  label,
  value: (s) => `${s.poll[k]} S  (${POLL_BOUNDS[k][0]}-${POLL_BOUNDS[k][1]})`,
  change: (s, d) => ({ ...s, poll: { ...s.poll, [k]: stepPoll(k, s.poll[k], d) } }),
});

const SETTING_ROWS: SettingRow[] = [
  { kind: "setting", id: "theme", label: "THEME", value: (s) => THEME_LABELS[s.theme], change: (s, d) => ({ ...s, theme: cycle(THEMES, s.theme, d) }) },
  { kind: "setting", id: "vim", label: "VIM MODE", value: (s) => (s.vim ? "ON" : "OFF"), change: (s) => ({ ...s, vim: !s.vim }) },
  {
    kind: "setting", id: "thousands", label: "THOUSANDS SEPARATOR",
    value: (s) => `${SEP_LABEL[s.numberFormat.thousands]}   ${fmtPrice(1234567.891)}`,
    change: (s, d) => {
      let t = cycle(THOUSANDS, s.numberFormat.thousands, d);
      if (t === s.numberFormat.decimal) t = cycle(THOUSANDS, t, d);
      return { ...s, numberFormat: { ...s.numberFormat, thousands: t } };
    },
  },
  {
    kind: "setting", id: "decimal", label: "DECIMAL MARK", value: (s) => SEP_LABEL[s.numberFormat.decimal],
    change: (s, d) => {
      const dec = cycle(DECIMALS, s.numberFormat.decimal, d);
      // Keep the pair distinct: 1,234.5 <-> 1.234,5
      const th = s.numberFormat.thousands === dec ? (dec === "," ? "." : ",") : s.numberFormat.thousands;
      return { ...s, numberFormat: { thousands: th, decimal: dec } };
    },
  },
  {
    kind: "setting", id: "clocks", label: "CLOCKS", value: (s) => s.clocks.join("  ").toUpperCase() + "   (ENTER TO EDIT)",
    enter: (s) => prefillCommand(`SETTINGS CLOCKS ${s.clocks.join(" ")}`),
  },
  { kind: "setting", id: "chart.range", label: "DEFAULT CHART RANGE", value: (s) => s.chart.range, change: (s, d) => ({ ...s, chart: { ...s.chart, range: cycle(CHART_RANGES, s.chart.range, d) } }) },
  { kind: "setting", id: "chart.type", label: "DEFAULT CHART TYPE", value: (s) => s.chart.type, change: (s, d) => ({ ...s, chart: { ...s.chart, type: cycle(CHART_TYPES, s.chart.type, d) } }) },
  poll("news", "NEWS REFRESH"),
  poll("movers", "MOVERS REFRESH"),
  poll("crypto", "CRYPTO REFRESH"),
  poll("sources", "SOURCE HEALTH POLL (NEXT START)"),
  {
    kind: "setting", id: "ai.model", label: "AI MODEL", value: (s) => `${s.ai.model}   (SETTINGS AI MODEL <ID> FOR ANY OTHER)`,
    change: (s, d) => ({ ...s, ai: { ...s.ai, model: cycle(AI_MODEL_CHOICES as readonly string[], s.ai.model, d) } }),
  },
  {
    kind: "setting", id: "ai.vision", label: "AI VISION MODEL", value: (s) => s.ai.visionModel,
    change: (s, d) => ({ ...s, ai: { ...s.ai, visionModel: cycle(AI_VISION_CHOICES as readonly string[], s.ai.visionModel, d) } }),
  },
  {
    kind: "setting", id: "ai.provider", label: "AI PROVIDER (KEY IN APIKEYS)", value: (s) => s.ai.provider.toUpperCase(),
    change: (s, d) => ({ ...s, ai: { ...s.ai, provider: cycle(AI_PROVIDERS, s.ai.provider, d) } }),
  },
  {
    kind: "setting", id: "ai.storeText", label: "KEEP AI QUESTION AND ANSWER TEXT (OFF: ONLY HASHES. ON: REDACTED TEXT STAYS ON THIS MACHINE NEXT TO THE AUDIT LEDGER, NEVER SENT; PURGE IN AUDIT)",
    value: (s) => (s.ai.storeText ? "ON" : "OFF") + "   (SETTINGS AI STORETEXT ON|OFF)",
    change: (s) => ({ ...s, ai: { ...s.ai, storeText: !s.ai.storeText } }),
  },
  {
    kind: "setting", id: "ai.web", label: "AI WEB ACCESS (STRANGERS' TEXT; SEE AI_WEB DOC)", value: (s) => (s.ai.web ? `ON, SEARCH VIA ${s.ai.webProvider.toUpperCase()}` : "OFF"),
    change: (s) => ({ ...s, ai: { ...s.ai, web: !s.ai.web } }),
  },
  // H / L cycle the presets. Any other installed font: SETTINGS FONT <name>.
  { kind: "setting", id: "font", label: "FONT (ANY INSTALLED: SETTINGS FONT NAME)", value: (s) => fontLabel(s.font), change: (s, d) => ({ ...s, font: cyclePreset(s.font, d).name }) },
  { kind: "setting", id: "startup", label: "ON START-UP OPEN (HOME PAGE OR YOUR LAST LAYOUT)", value: (s) => (s.startup === "home" ? "HOME PAGE" : "LAST LAYOUT"), change: (s, d) => ({ ...s, startup: cycle(STARTUPS, s.startup, d) }) },
  { kind: "setting", id: "tape", label: "TICKER TAPE IN THE TOP BAR (TAPE ADD / DEL / RESET EDITS IT)", value: (s) => (s.tape ? "ON" : "OFF"), change: (s) => ({ ...s, tape: !s.tape }) },
  // Last on purpose: the rows above keep their positions (THEME is first). Same switch as the status bar toggle and Alt+G.
  { kind: "setting", id: "mode", label: "INTERFACE MODE (TERMINAL OR GUI, ALT+G)", value: (s) => s.mode.toUpperCase(), change: (s, d) => ({ ...s, mode: cycle(MODES, s.mode, d) }) },
];

const MODIFIER_KEYS = new Set(["Control", "Alt", "Shift", "Meta", "AltGraph", "CapsLock"]);
const MAX_CHORDS = 4;

export default function SETTINGS({ panelId }: FunctionProps) {
  const settings = useStore(settingsStore, (s) => s);
  const bindings = effectiveBindings();
  const rows: Row[] = [...SETTING_ROWS, ...(Object.keys(bindings) as Action[]).map<KeyRow>((action) => ({ kind: "key", action }))];
  const [sel, setSel] = useState(0);
  const [capture, setCapture] = useState<{ action: Action; mode: "replace" | "add" } | null>(null);
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const state = useRef({ rows, sel, settings, capture, confirmReset });
  state.current = { rows, sel, settings, capture, confirmReset };
  const selRow = useRef<HTMLTableRowElement>(null);

  useEffect(() => {
    selRow.current?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const say = (text: string, err = false) => {
    setMsg({ text, err });
    if (!err) info(text);
  };

  const setChords = (action: Action, chords: string[]) => {
    const next = { ...effectiveBindings(), [action]: chords };
    updateSettings((s) => ({ ...s, keys: diffBindings(KEYBINDINGS, next) }));
  };

  // Chord capture: a capture-phase window listener so no global binding, panel key or browser default runs.
  useEffect(() => {
    if (!capture) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (MODIFIER_KEYS.has(e.key)) return; // wait for the real key
      setCapture(null);
      const plain = !e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey;
      if (plain && e.key === "Escape") return say("REBIND CANCELLED");
      const c = chord(e);
      const current = effectiveBindings()[capture.action];
      const check = checkChord(effectiveBindings(), capture.action, c, { vim: state.current.settings.vim });
      const sameAction = !check.ok && /ALREADY BOUND/.test(check.reason);
      if (!check.ok && !(sameAction && capture.mode === "replace")) return say(check.reason, true);
      if (capture.mode === "add" && current.length >= MAX_CHORDS) return say(`AT MOST ${MAX_CHORDS} SHORTCUTS PER ACTION`, true);
      setChords(capture.action, capture.mode === "add" ? [...current, c] : [c]);
      say(`${c} → ${ACTION_LABELS[capture.action].toUpperCase()}`);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [capture]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { rows: rs, sel: i, settings: s, confirmReset: cr } = state.current;
        const row = rs[Math.min(i, rs.length - 1)];
        if (cr && e.key !== "R" && !MODIFIER_KEYS.has(e.key)) setConfirmReset(false); // Shift keydown arrives before "R"
        const to = listNav(e.key, i, rs.length);
        if (to !== null) {
          setSel(to);
          return true;
        }
        if (row.kind === "setting") {
          const dir = e.key === "h" || e.key === "ArrowLeft" ? -1 : e.key === "l" || e.key === "ArrowRight" || e.key === "Enter" || e.key === " " ? 1 : 0;
          if (dir && row.change) {
            const next = updateSettings((cur) => row.change!(cur, dir));
            say(`${row.label} ${row.value(next)}`);
            return true;
          }
          if (e.key === "Enter" && row.enter) {
            row.enter(s);
            return true;
          }
        } else {
          const fixed = FIXED_ACTIONS.has(row.action);
          if (e.key === "Enter" || e.key === "a") {
            if (fixed) say("THIS SHORTCUT IS FIXED", true);
            else {
              setMsg({ text: `PRESS THE NEW SHORTCUT FOR ${ACTION_LABELS[row.action].toUpperCase()} (ESC CANCELS)`, err: false });
              setCapture({ action: row.action, mode: e.key === "a" ? "add" : "replace" });
            }
            return true;
          }
          if (e.key === "x" || e.key === "Delete") {
            if (!fixed) {
              setChords(row.action, [...KEYBINDINGS[row.action]]);
              say(`${ACTION_LABELS[row.action].toUpperCase()}: DEFAULT RESTORED`);
            }
            return true;
          }
        }
        if (e.key === "R") {
          if (cr) {
            setConfirmReset(false);
            resetSettings();
            say("SETTINGS RESET TO DEFAULTS");
          } else setConfirmReset(true);
          return true;
        }
        return false;
      }),
    [panelId],
  );

  const i = Math.min(sel, rows.length - 1);
  return (
    <div className="settings">
      <h2>SETTINGS</h2>
      <table className="t">
        <colgroup>
          <col style={{ width: 20 }} />
          <col style={{ width: 300 }} />
          <col />
        </colgroup>
        <tbody>
          {rows.map((r, k) => {
            const on = k === i;
            const head = r.kind === "key" && k === SETTING_ROWS.length;
            const cells =
              r.kind === "setting" ? (
                <>
                  <td>{r.label}</td>
                  <td className="acc">{r.value(settings)}</td>
                </>
              ) : (
                <>
                  <td>{ACTION_LABELS[r.action].toUpperCase()}</td>
                  <td>
                    {capture?.action === r.action ? (
                      <span className="warn">PRESS A KEY…</span>
                    ) : (
                      <>
                        <span className={settings.keys[r.action] ? "warn" : "acc"}>{bindings[r.action].join("  ") || "(UNBOUND)"}</span>
                        {FIXED_ACTIONS.has(r.action) && <span className="dim">  FIXED</span>}
                        {settings.keys[r.action] && !FIXED_ACTIONS.has(r.action) && <span className="dim">  CHANGED · DEFAULT {KEYBINDINGS[r.action].join("  ")}</span>}
                      </>
                    )}
                  </td>
                </>
              );
            return [
              head && (
                <tr key="keys-head">
                  <td />
                  <th colSpan={2}>SHORTCUTS</th>
                </tr>
              ),
              <tr key={r.kind === "key" ? r.action : r.id} ref={on ? selRow : undefined} className={on ? "on" : ""} aria-selected={on} data-row={r.kind === "key" ? r.action : r.id}>
                <td className="acc">{on ? ">" : ""}</td>
                {cells}
              </tr>,
            ];
          })}
        </tbody>
      </table>
      <div className={msg?.err ? "err" : "acc"} role="status">
        {confirmReset ? <span className="err">RESET ALL SETTINGS? PRESS SHIFT+R AGAIN</span> : (msg?.text ?? " ")}
      </div>
      <div className="dim">
        J K SELECT · H L / ← → / ENTER CHANGE · SHORTCUTS: ENTER REBIND · A ADD · X DEFAULT · SHIFT+R RESET ALL · SAVED AUTOMATICALLY
      </div>
    </div>
  );
}
