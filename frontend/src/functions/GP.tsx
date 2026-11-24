import { useEffect, useMemo, useRef, useState } from "react";
import { registerChartShot } from "../chart/shot";
import { CHART_TYPES, INTERVAL_S, ChartView, toBarData, type BarData, type ChartHandle, type ChartMarkerEvent, type CustomItem } from "../chart/ChartView";
import { isBrickType } from "../chart/brickNote";
import { onLink, publishLink } from "../chart/linkBus";
import { REPLAY_QTY, useReplay } from "./useReplay";
import { unrealized } from "../chart/replay";
import { onIndicatorRequest, setChartIndicators, type IndicatorRequest } from "../chart/indicatorBus";
import { alertDirection, fmtAlertPrice, roundAlertPrice } from "../chart/alertPrice";
import { createDrawSaver } from "../chart/drawSave";
import { ANCHOR_HINT, DRAW_KINDS, LABEL_MAX, MAX_DRAWINGS, NEEDED, KIND_NAME, TOOLS, cycleSelection, newId, parseDrawings, snapDay, type DPoint, type DrawKind, type Drawing } from "../chart/drawings";
import { PanelNote } from "../components/PanelNote";
import { isKeyRequired, KeyRequiredLine } from "./KeyRequiredLine";
import { INDICATORS } from "../chart/indicators";
import { fmtAge } from "../format";
import { alerts as alertStore } from "../command/alerts";
import { createPriceAlert } from "../command/priceAlert";
import { fail } from "../command/status";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { chartApi } from "../net/chartApi";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import type { ChartEvents, Envelope, FormulaInfo } from "../net/types";
import { subscribe } from "../net/socket";
import { symId } from "../state/symbols";
import { getLive, onTicks, SRC_LABEL } from "../state/ticks";
import { currentView, navigate, replaceView, workspace } from "../state/workspace";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { KEY_RANGES, MAX_CUSTOM, depthLimitFromError, formulaInd, libraryInd, limitText, longestRangeWithin, parseGpArgs, serializeGp, type GpParsed } from "./gpArgs";
import { fallbackText } from "./fallbackText";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import type { ConePoint } from "../chart/cone";
import { researchApi } from "../net/researchApi";

export { parseGpArgs };

/** Indicator picker keys: 1-9 then letters (I is left out: it closes the picker). */
const PICK_KEYS = "123456789ABCDEFGHJKLMNPQR"; // one key per INDICATORS entry, in order (I and O are skipped: they look like 1 and 0)
const ANCHOR_NAME = { C: "CLOSE", H: "HIGH", L: "LOW", O: "OPEN" } as const;
const ANCHOR_NEXT = { C: "H", H: "L", L: "O", O: "C" } as const;
/** Drawing tool picker (W): one key per DRAW_KINDS entry, in order (I and O skipped, as in the indicator picker). */
const TOOL_KEYS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZ";
/** The account / risk text last typed into a position tool, offered again for the next one (this page session only). */
let lastRiskText = "";

/** One row of the object tree (O): a drawing, or a study (built-in indicator or IND formula / library item). */
type TreeItem = { type: "draw"; d: Drawing } | { type: "study"; key: string; label: string; custom: boolean };

/** Text asked for after placing TEXT / NOTE / LONG / SHORT, or to rename a drawing from the object tree. */
interface Ask {
  kind: DrawKind;
  pts: DPoint[];
  /** Set when renaming (or re-wording) an existing drawing instead of adding one. */
  id?: string;
  text: string;
}

interface Loaded {
  bars: BarData;
  source: string | null;
  asOf: number;
  stale: boolean;
  fallback: string[];
  fallbackNotes?: Record<string, string>;
  formula?: FormulaInfo;
  compares: { symbol: string; t: Float64Array; c: Float64Array }[];
  compareErrors: string[];
}

/** The GP panel that answers IND requests: the focused GP, else the GP focused last. */
const gpLast: { id: number | null } = { id: null };

interface Mode {
  kind: DrawKind;
  pts: DPoint[];
  anchor: "C" | "H" | "L" | "O";
  /** E on a selected drawing re-places its anchors: the id it replaces (its text, name and flags are kept). */
  editing?: string;
}

export default function GP({ panelId, security, args, source }: FunctionProps) {
  const chartDefaults = useStore(settingsStore, (st) => st.chart);
  const p = useMemo(() => parseGpArgs(args, chartDefaults), [args, chartDefaults]);
  const symbol = security!.symbol;
  const [state, setState] = useState<{ loaded?: Loaded; error?: string; keyError?: ApiError; loading: boolean }>({ loading: true });
  const [picker, setPicker] = useState(false);
  const [toolPicker, setToolPickerState] = useState(false);
  const toolPickerRef = useRef(false);
  const setToolPicker = (on: boolean) => {
    toolPickerRef.current = on;
    setToolPickerState(on);
  };
  // Object tree (O): open flag + the row the cursor is on; studies hidden from it are kept here (this panel only).
  const [treeOpen, setTreeOpenState] = useState(false);
  const treeOpenRef = useRef(false);
  const setTreeOpen = (on: boolean) => {
    treeOpenRef.current = on;
    setTreeOpenState(on);
  };
  const [treeRow, setTreeRow] = useState(0);
  const [hiddenStudies, setHiddenStudies] = useState<ReadonlySet<string>>(() => new Set());
  const [ask, setAsk] = useState<Ask | null>(null);
  const [crossOn, setCrossOn] = useState(false);
  const [reload, setReload] = useState(0);
  const chart = useRef<ChartHandle>(null);
  const pRef = useRef(p);
  pRef.current = p;
  useEffect(() => registerChartShot(panelId, { symbol, range: p.range, shot: () => chart.current?.screenshot() ?? null }), [panelId, symbol, p.range]);

  // `pRef` moves on at once, so several changes in one tick (a preset adding 20 indicators) build on each other.
  const update = (fn: (q: GpParsed) => GpParsed) => {
    const next = fn(pRef.current);
    pRef.current = next;
    replaceView(panelId, (v) => ({ ...v, args: serializeGp(next, chartDefaults.type) }));
  };

  // The chosen candle length does not reach back that far (e.g. 5 min + 1Y on Yahoo). The server says so ("... ONLY AVAILABLE FOR THE
  // LAST 60 DAYS") and it knows which source answered, so the error text is the authority; this lets the note offer fixes.
  const depthDays = state.error ? depthLimitFromError(state.error) : null;
  const clash = depthDays !== null;

  // --- library indicators and formulas (IND): one GP answers, the same add/remove path as the toolbar toggles ---
  const [customErrors, setCustomErrors] = useState<Record<string, string>>({});
  // Studies hidden in the object tree are left out of what the chart draws (they stay in the panel's args).
  const custom = useMemo<CustomItem[]>(
    () => p.custom.filter((c) => !hiddenStudies.has(c.key)).map((c) => ({ key: c.key, label: c.label, id: c.id, params: c.params, formula: c.formula })),
    [p.custom, hiddenStudies],
  );
  const shownIndicators = useMemo(() => p.indicators.filter((n) => !hiddenStudies.has(n)), [p.indicators, hiddenStudies]);
  const customKeys = p.custom.map((c) => c.key);
  const customKeyStr = customKeys.join("\n");
  const isAnswering = () => {
    const f = workspace.get().focus;
    const fv = workspace.get().panels[f];
    return f === panelId || (gpLast.id === panelId && (!fv || currentView(fv).fn !== "GP"));
  };
  useEffect(() => {
    const track = () => {
      // A GP mounted while nothing else claims the role (reloaded layout, remount after a split) takes it.
      if (workspace.get().focus === panelId || gpLast.id === null) gpLast.id = panelId;
      if (isAnswering()) setChartIndicators(pRef.current.custom.map((c) => c.key));
    };
    track();
    const off = workspace.subscribe(track);
    const offReq = onIndicatorRequest((req: IndicatorRequest) => {
      if (!isAnswering()) return false;
      const ind = "formula" in req ? formulaInd(req.formula) : libraryInd(req.id, req.params ?? []);
      const has = pRef.current.custom.some((c) => c.key === ind.key);
      if (has && req.op !== "toggle") return true;
      if (!has && pRef.current.custom.length >= MAX_CUSTOM) {
        fail(`AT MOST ${MAX_CUSTOM} CUSTOM INDICATORS ON ONE CHART`);
        return true;
      }
      update((q) => ({ ...q, custom: has ? q.custom.filter((c) => c.key !== ind.key) : [...q.custom, ind] }));
      return true;
    });
    return () => {
      off();
      offReq();
      if (gpLast.id === panelId) {
        gpLast.id = null;
        setChartIndicators([]);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keys and cleanup are set up once per panel; handlers read current state through `pRef` and stable setters
  }, [panelId]);
  useEffect(() => {
    if (isAnswering()) setChartIndicators(customKeyStr ? customKeyStr.split("\n") : []);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- customKeyStr is the re-run trigger; isAnswering reads the workspace store at call time
  }, [customKeyStr]);

  // --- bars (and compare symbols) ---
  const compareKey = p.compare.join(",");
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    const main = marketApi.history(symbol, p.range, p.interval, false, source);
    const cmp = Promise.all(p.compare.map((c) => marketApi.history(c, p.range, p.interval, false, source).catch((e: ApiError) => e)));
    Promise.all([main, cmp])
      .then(([env, cs]) => {
        if (!alive) return;
        const compares: Loaded["compares"] = [];
        const compareErrors: string[] = [];
        cs.forEach((c, i) => {
          if (c instanceof ApiError) compareErrors.push(`${p.compare[i]}: ${c.message}`);
          else compares.push({ symbol: c.data.symbol, ...pick(toBarData(c.data)) });
        });
        setState({
          loading: false,
          loaded: { bars: toBarData(env.data), source: env.source, asOf: env.as_of, stale: env.stale, fallback: env.fallback_from, fallbackNotes: env.fallback_notes, formula: env.formula, compares, compareErrors },
        });
      })
      .catch((e: ApiError) => alive && setState({ loading: false, error: e.message, keyError: isKeyRequired(e) ? e : undefined }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- p.compare is tracked through compareKey (p changes identity every render); `reload` is the manual refetch trigger
  }, [symbol, p.range, p.interval, compareKey, reload, source]);

  // Live: extend the last bar from ticks.
  const resolved = state.loaded?.source === "formula" || p.replay ? undefined : state.loaded?.bars.symbol;
  useEffect(() => {
    if (!resolved) return;
    const unsub = subscribe([resolved]);
    const id = symId(resolved);
    const off = onTicks((batch) => {
      if (!batch.has(id)) return;
      const l = getLive(resolved)!;
      chart.current?.live(l.price, l.t, l.volume);
    });
    return () => {
      unsub();
      off();
    };
    // Only the symbol matters: the callback reads `chart` (a ref) and the live store, so a history reload
    // (range / candle change, refresh) must not unsubscribe and resubscribe the same symbol.
  }, [resolved]);

  // --- drawings: stored per symbol on the server, saved 0.4 s after the last change ---
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setModeState] = useState<Mode | null>(null);
  // The key handler reads the draw mode from this ref, which changes in the same call as the state: two keys pressed
  // within one frame (key repeat, Playwright) must see each other's effect, not the last render's.
  const modeRef = useRef<Mode | null>(null);
  const setMode = (m: Mode | null) => {
    modeRef.current = m;
    setModeState(m);
  };
  const [drawNote, setDrawNote] = useState<string | null>(null);
  // One saver per panel: it saves to the symbol the loaded list belongs to, so a symbol switch in place cannot mis-address a save.
  const saver = useMemo(() => createDrawSaver((sym, list) => chartApi.saveDrawings(sym, list), setDrawNote), []);
  useEffect(() => {
    let alive = true;
    saver.reset();
    setDrawings([]);
    setSelected(null);
    setMode(null);
    chartApi
      .drawings(symbol)
      .then((r) => {
        if (!alive) return;
        setDrawings(parseDrawings(r.drawings));
        saver.loaded(symbol);
        setDrawNote(null);
      })
      .catch((e: ApiError) => alive && setDrawNote(`DRAWINGS NOT LOADED: ${e.message}`));
    return () => {
      alive = false;
      saver.flush();
    };
  }, [symbol, saver]);
  const commit = (next: Drawing[]) => {
    setDrawings(next);
    saver.change(next);
  };

  // --- event markers (EVT) ---
  const [events, setEvents] = useState<{ env?: Envelope<ChartEvents>; error?: string } | null>(null);
  useEffect(() => {
    if (!p.evt) {
      setEvents(null);
      return;
    }
    let alive = true;
    chartApi
      .events(symbol, reload > 0)
      .then((env) => alive && setEvents({ env }))
      .catch((e: ApiError) => alive && setEvents({ error: `${e.message}${e.detail ? ` (${e.detail})` : ""}` }));
    return () => {
      alive = false;
    };
  }, [symbol, p.evt, reload]);

  const L = state.loaded;
  // Phase 24: bar replay. The chart is given only the revealed bars (`rp.shown`), so no study can see a hidden one.
  const rp = useReplay(panelId, L?.bars, p.replay, linkGroupForReplay(panelId), symbol);
  const markers = useMemo<ChartMarkerEvent[] | undefined>(() => {
    if (!L || !p.evt || !events?.env) return undefined;
    const iv = INTERVAL_S[L.bars.interval] ?? 86400;
    return events.env.data.events.flatMap((e) => {
      const t = snapDay(e.date, L.bars.t, iv);
      return t === null ? [] : [{ t, kind: e.kind, detail: `${e.date} ${e.detail}` }];
    });
  }, [L, p.evt, events]);

  const drawState = useMemo(() => ({ drawings, selected, pending: mode }), [drawings, selected, mode]);
  // --- alert from the chart: key A (crosshair or last price), Shift+A or the toolbar button arms one click, Alt+click always ---
  const [armed, setArmed] = useState(false);
  const allAlerts = useStore(alertStore, (a) => a);
  const alertKey = (allAlerts ?? [])
    .filter((a) => a.status === "active" && a.unit === "price" && a.symbol === (L?.bars.symbol ?? symbol))
    .map((a) => a.value)
    .sort((a, b) => a - b)
    .join(",");
  // Phase 28: `CONE` loads the options' per-expiry ranges once per symbol; an error is shown, never a made-up cone.
  const [cone, setCone] = useState<{ points: ConePoint[]; label: string } | { error: string } | null>(null);
  useEffect(() => {
    if (!p.cone) {
      setCone(null);
      return;
    }
    let alive = true;
    researchApi
      .cone(symbol)
      .then((e) => alive && setCone({ points: e.data.points, label: e.data.label }))
      .catch((e: ApiError) => alive && setCone({ error: e.message }));
    return () => {
      alive = false;
    };
  }, [p.cone, symbol]);
  const alertLevels = useMemo(() => (alertKey ? alertKey.split(",").map(Number) : []), [alertKey]);
  const placeAlert = (raw: number | null) => {
    const sym = L?.bars.symbol ?? symbol;
    const last = chart.current?.lastPrice() ?? null;
    if (raw === null || last === null || !Number.isFinite(raw)) return fail("NO PRICE YET");
    const price = roundAlertPrice(raw);
    if (price === null) return fail("ALERT PRICE MUST BE ABOVE 0");
    void createPriceAlert(sym, alertDirection(price, last), fmtAlertPrice(price));
    return true;
  };
  const overlayOn = !p.pane && !!L?.compares.length;
  useEffect(() => setArmed(false), [symbol, panelId]);
  const treeItems: TreeItem[] = [
    ...drawings.map((d): TreeItem => ({ type: "draw", d })),
    ...p.indicators.map((n): TreeItem => ({ type: "study", key: n, label: n, custom: false })),
    ...p.custom.map((c): TreeItem => ({ type: "study", key: c.key, label: c.label, custom: true })),
  ];
  // Brick charts (Renko, Kagi, P&F, line break, range bars) have their own non-linear time axis: indicators, compare
  // symbols and drawings are anchored on the source bars' clock, so they are switched off there (and the panel says so).
  const brick = isBrickType(p.type);
  const [chartNote, setChartNote] = useState<string | null>(null);

  // --- Phase 22: chart sync inside the panel's link group (LINK A..D; what is shared: SETTINGS LINK) ---
  const linkGroup = useStore(workspace, (s) => s.panels[panelId]?.link);
  const linkOn = useStore(settingsStore, (st) => st.link);
  const sync = useMemo(
    () => (linkGroup && !brick ? { group: linkGroup, panelId, crosshair: linkOn.crosshair, range: linkOn.range } : undefined),
    [linkGroup, brick, panelId, linkOn.crosshair, linkOn.range],
  );
  // A candle-length change made HERE is sent to the group (not the first value on mount, or a layout load would reset everyone).
  const sentInterval = useRef(p.interval);
  useEffect(() => {
    if (sentInterval.current === p.interval) return;
    sentInterval.current = p.interval;
    if (linkGroup && linkOn.interval) publishLink({ group: linkGroup, from: panelId, kind: "interval", interval: p.interval });
  }, [p.interval, linkGroup, linkOn.interval, panelId]);
  useEffect(
    () =>
      onLink((m) => {
        if (m.kind !== "interval" || m.group !== linkGroup || m.from === panelId || !linkOn.interval) return;
        if (m.interval === pRef.current.interval) return;
        sentInterval.current = m.interval; // taken from the group: do not send it back
        update((q) => ({ ...q, interval: m.interval }));
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `update` writes through pRef; re-subscribe only when the group or switch changes
    [linkGroup, linkOn.interval, panelId],
  );
  const live = useLatest({ drawings, selected, mode, bars: L?.bars, armed, placeAlert, overlayOn, treeItems, treeRow, brick });

  /**
   * All anchors are in: add the drawing (or, for E, replace the edited one's anchors). Tools that need words (TEXT, NOTE)
   * or the account / risk % (LONG, SHORT) first open the text box; it calls `addDrawing` when the user presses Enter.
   */
  const placeDrawing = (m: Mode, pts: DPoint[]) => {
    const st = live.current;
    setMode(null);
    if (m.editing) {
      commit(st.drawings.map((d) => (d.id === m.editing ? { ...d, pts } : d)));
      setSelected(m.editing);
      return true;
    }
    const want = TOOLS[m.kind].ask;
    if (want) {
      setAsk({ kind: m.kind, pts, text: want === "RISK" ? lastRiskText : "" });
      return true;
    }
    return addDrawing({ id: "", kind: m.kind, pts });
  };
  const addDrawing = (d: Drawing) => {
    const st = live.current;
    if (st.drawings.length >= MAX_DRAWINGS) {
      setDrawNote(`AT MOST ${MAX_DRAWINGS} DRAWINGS PER SYMBOL: DELETE ONE FIRST`);
      return true;
    }
    const id = newId(st.drawings);
    commit([...st.drawings, { ...d, id }]);
    setSelected(id);
    return true;
  };
  /** The text box's Enter: a new TEXT / NOTE / position tool, or a rename from the object tree. */
  const submitAsk = (a: Ask) => {
    const text = a.text.trim().slice(0, LABEL_MAX);
    if (!text && (a.kind === "TEXT" || a.kind === "NOTE")) return setDrawNote("TYPE THE TEXT FIRST (ESC CANCELS)");
    if (TOOLS[a.kind].ask === "RISK") lastRiskText = text;
    setAsk(null);
    setDrawNote(null);
    const withLabel = (d: Drawing): Drawing => {
      const { label: _old, ...rest } = d;
      return text ? { ...rest, label: text } : rest;
    };
    if (a.id) commit(live.current.drawings.map((d) => (d.id === a.id ? withLabel(d) : d)));
    else addDrawing(withLabel({ id: "", kind: a.kind, pts: a.pts }));
  };
  /** Object tree actions on the row under the cursor. Studies can be hidden or removed; drawings also renamed and locked. */
  const treeAction = (k: string) => {
    const st = live.current;
    const item = st.treeItems[st.treeRow];
    if (!item) return;
    if (item.type === "study") {
      if (k === "v" || k === " ") {
        setHiddenStudies((s) => {
          const n = new Set(s);
          if (n.has(item.key)) n.delete(item.key);
          else n.add(item.key);
          return n;
        });
      } else if (k === "d" || k === "Delete") {
        update((q) => (item.custom ? { ...q, custom: q.custom.filter((c) => c.key !== item.key) } : { ...q, indicators: q.indicators.filter((n) => n !== item.key) }));
      } else if (k === "r" || k === "l") fail("A STUDY CANNOT BE RENAMED OR LOCKED: HIDE (V) OR REMOVE (D) IT");
      return;
    }
    const d = item.d;
    const patch = (fn: (x: Drawing) => Drawing) => commit(st.drawings.map((x) => (x.id === d.id ? fn(x) : x)));
    if (k === "v" || k === " ") patch((x) => (x.hidden ? (({ hidden: _h, ...r }) => r)(x) : { ...x, hidden: true }));
    else if (k === "l") patch((x) => (x.locked ? (({ locked: _l, ...r }) => r)(x) : { ...x, locked: true }));
    else if (k === "r") setAsk({ kind: d.kind, pts: d.pts, id: d.id, text: d.label ?? "" });
    else if (k === "d" || k === "Delete") {
      if (d.locked) return fail("LOCKED: PRESS L TO UNLOCK IT FIRST");
      commit(st.drawings.filter((x) => x.id !== d.id));
      if (st.selected === d.id) setSelected(null);
    } else if (k === "Enter") {
      setSelected(d.id);
      setTreeOpen(false);
    }
  };

  usePanelRefresh(panelId, () => { setReload((r) => r + 1); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const k = e.key;
        if (picker) {
          const idx = PICK_KEYS.indexOf(k.toUpperCase());
          if (k.length === 1 && idx >= 0 && idx < INDICATORS.length) {
            const name = INDICATORS[idx];
            update((q) => ({ ...q, indicators: q.indicators.includes(name) ? q.indicators.filter((x) => x !== name) : [...q.indicators, name] }));
            return true;
          }
          if (k === "Escape" || k === "i") {
            setPicker(false);
            return true;
          }
          return true; // picker is modal inside the panel
        }
        const st = live.current;
        const plain = !e.ctrlKey && !e.altKey && !e.metaKey;
        if (toolPickerRef.current) {
          // Drawing tool picker: a key starts that tool, W or Esc closes. Modal like the indicator picker.
          const idx = TOOL_KEYS.indexOf(k.toUpperCase());
          if (k === "Escape" || k === "w") setToolPicker(false);
          else if (k.length === 1 && idx >= 0 && idx < DRAW_KINDS.length) {
            setToolPicker(false);
            if (st.bars) {
              if (!crossOn) {
                chart.current?.crosshair(true);
                setCrossOn(true);
              }
              setSelected(null);
              setMode({ kind: DRAW_KINDS[idx], pts: [], anchor: "C" });
            }
          }
          return true;
        }
        if (treeOpenRef.current) {
          // Object tree: arrows / J K move, V or Space hides, D removes, R renames, L locks, Enter selects, O or Esc closes.
          if (k === "Escape" || k === "o") setTreeOpen(false);
          else if (k === "ArrowDown" || k === "j") setTreeRow(Math.min(st.treeItems.length - 1, st.treeRow + 1));
          else if (k === "ArrowUp" || k === "k") setTreeRow(Math.max(0, st.treeRow - 1));
          else if (plain) treeAction(k);
          return true;
        }
        if (st.armed && k === "Escape") {
          setArmed(false);
          return true;
        }
        if (plain && !modeRef.current) {
          if (k === "a") {
            st.placeAlert(chart.current?.alertPrice() ?? null);
            return true;
          }
          if (k === "A") {
            if (!st.bars) return fail("NO PRICE YET");
            if (st.overlayOn) return fail("ALERT FROM THE CHART NEEDS THE PLAIN PRICE CHART: REMOVE VS FIRST");
            setArmed(!st.armed);
            return true;
          }
        }
        if (modeRef.current && plain) {
          if (k === "Escape") {
            setMode(null);
            return true;
          }
          if (k === "p") {
            setMode({ ...modeRef.current, anchor: ANCHOR_NEXT[modeRef.current.anchor] });
            return true;
          }
          if (k === "Enter") {
            const b = st.bars;
            if (!b || !chart.current) return true;
            const i = chart.current.crosshairIndex();
            const px = modeRef.current.anchor === "H" ? b.h[i] : modeRef.current.anchor === "L" ? b.l[i] : modeRef.current.anchor === "O" ? b.o[i] : b.c[i];
            if (!Number.isFinite(px) || !Number.isFinite(b.t[i])) return true;
            const pts = [...modeRef.current.pts, { t: b.t[i], p: px }];
            // A path takes 2 to 10 anchors: Shift+Enter places the last one. Every other tool ends at its anchor count.
            const spec = TOOLS[modeRef.current.kind];
            if (pts.length < spec.max && !(e.shiftKey && pts.length >= spec.min)) {
              setMode({ ...modeRef.current, pts });
              return true;
            }
            return placeDrawing(modeRef.current, pts);
          }
        }
        if (plain && !modeRef.current && st.brick && "thbwe".includes(k) && k.length === 1) return !fail("DRAWINGS NEED A TIME-BASED CHART TYPE: PRESS C FOR THE NEXT TYPE"); // handled: the key must not fall through
        if (plain && !modeRef.current) {
          const start = (kind: DrawKind) => {
            if (!st.bars) return true;
            if (!crossOn) {
              chart.current?.crosshair(true);
              setCrossOn(true);
            }
            setSelected(null);
            setMode({ kind, pts: [], anchor: "C" });
            return true;
          };
          if (k === "t") return start("TREND");
          if (k === "h") return start("HLINE");
          if (k === "b") return start("FIB");
          if (k === "w") {
            if (!st.bars) return true;
            setToolPicker(true);
            return true;
          }
          if (k === "o") {
            setTreeRow(0);
            setTreeOpen(true);
            return true;
          }
          if (k === "]" || k === "[") {
            setSelected(cycleSelection(st.drawings, st.selected, k === "]" ? 1 : -1));
            return true;
          }
          const sd = st.drawings.find((d) => d.id === st.selected);
          if ((k === "Delete" || k === "d") && sd) {
            if (sd.locked) return !fail("LOCKED: UNLOCK IT IN THE OBJECT TREE (O, THEN L)");
            commit(st.drawings.filter((d) => d.id !== st.selected));
            setSelected(null);
            return true;
          }
          if (k === "e" && sd) {
            // Re-place the selected drawing's anchors with the crosshair, keeping its text, name and flags.
            if (sd.locked) return !fail("LOCKED: UNLOCK IT IN THE OBJECT TREE (O, THEN L)");
            if (!crossOn) {
              chart.current?.crosshair(true);
              setCrossOn(true);
            }
            setMode({ kind: sd.kind, pts: [], anchor: "C", editing: sd.id });
            return true;
          }
          if (k === "Escape" && st.selected) {
            setSelected(null);
            return true;
          }
        }
        const n = Number(k);
        if (n >= 1 && n <= 8) {
          // Change only the range; keep the candle length the user picked (it used to snap back to Auto here).
          update((q) => ({ ...q, range: KEY_RANGES[n - 1] }));
          return true;
        }
        switch (k) {
          case "c":
            update((q) => ({ ...q, type: CHART_TYPES[(CHART_TYPES.indexOf(q.type) + 1) % CHART_TYPES.length] }));
            return true;
          case "l":
            update((q) => ({ ...q, log: !q.log }));
            return true;
          case "i":
            setPicker(true);
            return true;
          case "x": {
            const on = !crossOn;
            chart.current?.crosshair(on);
            setCrossOn(on);
            return true;
          }
          case "ArrowLeft":
            if (crossOn) chart.current?.crosshairStep(-1);
            else chart.current?.pan(-10);
            return true;
          case "ArrowRight":
            if (crossOn) chart.current?.crosshairStep(1);
            else chart.current?.pan(10);
            return true;
          case "+":
          case "=":
            chart.current?.zoom(0.8);
            return true;
          case "-":
            chart.current?.zoom(1.25);
            return true;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- key handler reads current state through `live` and the mode / picker / tree refs; re-register only when the panel, the indicator picker or crosshair mode changes
    [panelId, picker, crossOn],
  );

  const liveQ = L ? getLive(L.bars.symbol) : undefined;
  const sel = drawings.find((d) => d.id === selected);
  const overlayCompare = !p.pane && L?.compares.length ? L.compares[0] : null;
  const shownEvents = markers?.length ?? 0;
  return (
    <div className="fn gp" style={{ position: "relative" }}>
      <div className="line">
        <span className="acc">{L?.bars.symbol ?? symbol}</span> {p.range} {L?.bars.interval ?? p.interval ?? ""}{" "}
        {p.compare.length ? `VS ${p.compare.join(" ")} ${p.pane ? "(PANES)" : "(%)"}` : p.type}
        {p.log && !overlayCompare && " LOG"} {p.indicators.join(" ")} {p.custom.map((c) => c.label).join(" ")}
        {L && (
          <span className="dim">
            {" · "}
            {L.source === "local" ? "LOCAL DATA (IMPORTED BY YOU)" : L.source?.toUpperCase()} AS OF {fmtAge(Math.max(0, Date.now() / 1000 - L.asOf))} AGO
            {liveQ && ` · LIVE ${SRC_LABEL[liveQ.src] ?? ""}`}
          </span>
        )}
        {L?.stale && <span className="warn"> · STALE</span>}
        {L?.formula && <FormulaNote f={L.formula} />}
        {rp.active && <ReplayLine r={rp} />}
        {cone && <span data-testid="gp-cone" className={"error" in cone ? "err" : "dim"}> · CONE: {"error" in cone ? cone.error : cone.label}</span>}
        {L?.fallback.length ? <span className="warn"> · {fallbackText(L.fallback, L.fallbackNotes)}</span> : null}
        {L?.compareErrors.map((m) => (
          <span className="err" key={m}> · {m}</span>
        ))}
        {state.loading && <span className="dim"> · LOADING…</span>}
        {crossOn && !mode && <span className="acc"> · CROSSHAIR (←/→, X TO EXIT)</span>}
        {mode && (
          <span className="acc" data-testid="gp-draw-mode">
            {" · "}{mode.editing ? "MOVE" : "DRAW"} {KIND_NAME[mode.kind]}: {ANCHOR_HINT[mode.kind]?.[mode.pts.length] ?? "ANCHOR"} {mode.pts.length + 1}/{NEEDED[mode.kind]} AT {ANCHOR_NAME[mode.anchor]} · ←/→ MOVE · P PRICE · ENTER PLACES
            {mode.kind === "PATH" && mode.pts.length >= 1 && " · SHIFT+ENTER PLACES THE LAST"} · ESC CANCELS
          </span>
        )}
        {!mode && sel && (
          <span className="acc"> · {KIND_NAME[sel.kind]} {sel.label ? `"${sel.label}" ` : ""}{sel.id} SELECTED{sel.locked ? " (LOCKED)" : ""} · [ ] CYCLE · E MOVES · D REMOVES</span>
        )}
        {armed && <span className="acc"> · CLICK THE CHART TO SET AN ALERT, ESC TO CANCEL</span>}
        {drawNote && <span className="err"> · {drawNote}</span>}
        {Object.values(customErrors).map((m) => (
          <span className="err" key={m} data-testid="gp-custom-err"> · {m}</span>
        ))}
        <span className="dim legend"> · 1-8 RANGE · C TYPE · I IND · L LOG · ←/→ PAN · +/- ZOOM · X CROSS · W DRAWING TOOLS · T/H/B DRAW (QUICK) · O OBJECTS · A ALERT (SHIFT+A OR ALT+CLICK: AT A CLICKED PRICE) · CHARTS: TRADINGVIEW LIGHTWEIGHT CHARTS</span>
      </div>
      {ask && (
        <div className="line">
          <span className="acc">
            {ask.id ? `RENAME ${KIND_NAME[ask.kind]}` : TOOLS[ask.kind].ask === "RISK" ? `${KIND_NAME[ask.kind]}: ACCOUNT SIZE AND RISK % (E.G. 100000 1), OR EMPTY` : `${KIND_NAME[ask.kind]} TEXT`}
            {" "}
          </span>
          <input
            data-testid="gp-draw-text"
            autoFocus
            maxLength={LABEL_MAX}
            value={ask.text}
            onChange={(e) => setAsk({ ...ask, text: e.target.value })}
            onKeyDown={(e) => {
              // Plain keys belong to the box; Ctrl / Alt / Meta chords bubble so Ctrl+K and the other global keys still work.
              if (!e.ctrlKey && !e.altKey && !e.metaKey) e.stopPropagation();
              if (e.key === "Enter") submitAsk(ask);
              else if (e.key === "Escape") {
                setAsk(null);
                setDrawNote(null);
              }
            }}
          />
          <span className="dim"> ENTER SAVES · ESC CANCELS</span>
        </div>
      )}
      {p.evt && (
        <div className="line dim">
          {events?.error ? <span className="err">EVT: {events.error}</span> : !events ? "EVT: LOADING…" : (
            <>
              EVT E=EARNINGS (LAST 4 REPORTED) D=EX-DIVIDEND S=SPLIT · {shownEvents} IN VIEW OF {events.env!.data.events.length} · {events.env!.source?.toUpperCase()}
              {events.env!.data.missing.length ? <span className="warn"> · MISSING {events.env!.data.missing.join(", ")}</span> : null}
            </>
          )}
        </div>
      )}
      {chartNote && (
        <div className="line dim" data-testid="gp-chart-note">
          {chartNote}
          {brick && (p.indicators.length || p.custom.length || p.compare.length || drawings.length) ? " · INDICATORS, COMPARE AND DRAWINGS ARE OFF ON A BRICK CHART" : ""}
        </div>
      )}
      {p.indicators.includes("PAT:GEO") && !brick && (
        <div className="line dim" data-testid="gp-geo-note">PAT:GEO: SHAPES FROM SWING PIVOTS (ZIGZAG 2 X ATR14) · PATTERN RULE, NOT A SIGNAL</div>
      )}
      {overlayCompare && drawings.length > 0 && <div className="warn">DRAWINGS HIDDEN WHILE A % OVERLAY (VS) IS ON: USE PANE TO KEEP THEM</div>}
      {p.compare.length > 1 && !p.pane && <div className="warn">VS OVERLAYS ONLY {p.compare[0]}; ADD PANE TO SHOW ALL {p.compare.length}</div>}
      {/* Same look as every other panel (components/PanelNote): the error keeps its text, the hint says what to do next. */}
      {state.keyError && !L && <KeyRequiredLine error={state.keyError} />}
      {state.error && !state.keyError && !L && (
        <PanelNote
          kind="error"
          hint={clash ? "PICK A LONGER CANDLE (AUTO) OR A SHORTER RANGE." : "F5 TO RETRY."}
          // GUI wording: a symbol the user picked is valid, so never blame the spelling here; say what is actually wrong.
          plain={
            clash
              ? `The data source only has ${p.interval ?? "these"} candles ${limitText(depthDays!)} back, and ${p.range} is longer than that. Your candle length is kept; pick one of the fixes below.`
              : /NO DATA|NOT FOUND/i.test(state.error)
                ? `No chart data came back for ${symbol} over ${p.range}. The name is fine: the data source has nothing for it right now (in sample-data mode that can be a gap in the recordings). Retry, try another range, or chart a different stock.`
                : undefined
          }
          actions={[
            ...(clash
              ? [
                  { label: "Use Auto candles", onClick: () => update((q) => ({ ...q, interval: undefined })) },
                  ...(longestRangeWithin(depthDays!) ? [{ label: `Show ${longestRangeWithin(depthDays!)} instead`, onClick: () => update((q) => ({ ...q, range: longestRangeWithin(depthDays!)! })) }] : []),
                ]
              : []),
            ...(symbol !== "AAPL" ? [{ label: "Try AAPL", onClick: () => navigate(panelId, { fn: "GP", security: { symbol: "AAPL" }, args: [] }) }] : []),
          ]}
          onRetry={() => setReload((n) => n + 1)}
        >
          {state.error} ({symbol} {p.range}).
        </PanelNote>
      )}
      {!L && !state.error && <PanelNote kind="loading">LOADING {symbol} {p.range}…</PanelNote>}
      {L && (
        <ChartView
          ref={chart}
          data={rp.shown ?? L.bars}
          compare={brick ? null : overlayCompare}
          type={p.type}
          log={p.log}
          brickBox={p.box}
          brickRev={p.rev}
          onNote={setChartNote}
          sync={sync}
          // Everything only GP needs goes in one `gp` object (see chart/gpLayer.ts).
          gp={{
            indicators: brick ? [] : shownIndicators,
            comparePanes: p.pane && !brick ? L.compares : undefined,
            custom: brick ? [] : custom,
            onCustomErrors: setCustomErrors,
            draw: brick ? undefined : drawState,
            events: brick ? undefined : markers,
            onPick: (id) => setSelected(id),
            alertLevels,
            cone: cone && "points" in cone ? cone.points : undefined,
            pickArmed: armed,
            onPickPrice: (px) => {
              setArmed(false);
              live.current.placeAlert(px);
            },
          }}
        />
      )}
      {picker && (
        <div className="picker">
          <div className="acc">INDICATORS (KEY TOGGLES, ESC CLOSES)</div>
          {INDICATORS.map((name, i) => (
            <div key={name}>
              {PICK_KEYS[i]} {p.indicators.includes(name) ? "[X]" : "[ ]"} {name}
            </div>
          ))}
        </div>
      )}
      {toolPicker && (
        <div className="picker" data-testid="gp-tools">
          <div className="acc">DRAWING TOOLS (KEY STARTS ONE, ESC CLOSES)</div>
          {DRAW_KINDS.map((k, i) => (
            <div key={k}>
              {TOOL_KEYS[i]} {KIND_NAME[k]}
            </div>
          ))}
        </div>
      )}
      {treeOpen && (
        <div className="picker" data-testid="gp-tree">
          <div className="acc">OBJECTS · ↑/↓ MOVE · V HIDE · D REMOVE · R RENAME · L LOCK · ENTER SELECT · ESC CLOSES</div>
          {!treeItems.length && <div className="dim">NOTHING ON THIS CHART YET: W DRAWS, I ADDS INDICATORS</div>}
          {treeItems.map((it, i) => {
            const hidden = it.type === "draw" ? !!it.d.hidden : hiddenStudies.has(it.key);
            const name = it.type === "draw" ? `${KIND_NAME[it.d.kind]}${it.d.label ? ` "${it.d.label}"` : ""} ${it.d.id}` : `STUDY ${it.label}`;
            return (
              <div key={it.type === "draw" ? it.d.id : `s:${it.key}`} className={i === treeRow ? "sel" : undefined} data-testid="gp-tree-row">
                {hidden ? "[ ]" : "[X]"} {name}
                {it.type === "draw" && it.d.locked ? " LOCKED" : ""}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function pick(b: BarData) {
  return { t: b.t, c: b.c };
}

/** Phase 22: what a computed series (`AAPL/MSFT`) is made of: each leg's source and age, and every bar the join left out. */
function FormulaNote({ f }: { f: FormulaInfo }) {
  const dropped = f.dropped_join + f.incomplete + f.dropped_zero;
  return (
    <span className="dim" data-testid="gp-formula">
      {" · "}
      {f.name ? `${f.name} = ${f.text} · ` : ""}
      {f.legs.map((l) => `${l.symbol} ${(l.source ?? "?").toUpperCase()} ${fmtAge(l.age_s)}${l.stale ? " STALE" : ""}`).join(" · ")}
      {dropped > 0 && (
        <span className="warn">
          {" · "}
          {[
            f.dropped_join && `${f.dropped_join} BARS NOT IN EVERY LEG`,
            f.incomplete && `${f.incomplete} INCOMPLETE`,
            f.dropped_zero && `${f.dropped_zero} DIVIDED BY ZERO`,
          ].filter(Boolean).join(", ")}{" "}
          DROPPED
        </span>
      )}
      {f.utc_fallback.length > 0 && <span className="warn"> · {f.utc_fallback.join(" ")} ZONE UNKNOWN: JOINED ON UTC DATES</span>}
    </span>
  );
}

/** The panel's link group, read once per render for the replay clock (the full link logic lives further down in GP). */
function linkGroupForReplay(panelId: number): string | undefined {
  return workspace.get().panels[panelId]?.link;
}

/** Phase 24: where the replay is and what the practice book holds. */
function ReplayLine({ r }: { r: ReturnType<typeof useReplay> }) {
  const b = r.book;
  const t = r.shown && r.shown.t.length ? new Date(r.shown.t[r.shown.t.length - 1] * 1000).toISOString().slice(0, 10) : "";
  const pnl = b.realized + unrealized(b, r.last);
  return (
    <span data-testid="gp-replay">
      <span className="warn"> · REPLAY {t} BAR {r.n}/{r.total} {r.playing ? `PLAYING ${r.speed}/S` : "PAUSED"}</span>
      <span className="dim">
        {" "}· PRACTICE {b.qty > 0 ? "+" : ""}{b.qty}{b.qty ? ` @ ${b.avg.toFixed(2)}` : ""}
        {b.pending.length ? ` · ${b.pending.length} ORDER(S) AT NEXT OPEN` : ""} · P&amp;L{" "}
      </span>
      <span className={pnl > 0 ? "up" : pnl < 0 ? "down" : "dim"}>{pnl.toFixed(2)}</span>
      <span className="dim"> · . NEXT , BACK SPACE PLAY S SPEED · SHIFT+B BUY {REPLAY_QTY} SHIFT+S SELL SHIFT+F FLAT SHIFT+J SAVE TO JRNL</span>
    </span>
  );
}
