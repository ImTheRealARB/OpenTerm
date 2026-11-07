/**
 * DLVR: where alerts and the daily brief get delivered (Phase 17 B/C). A small DOM table, not a canvas grid:
 * it has a handful of rows and each row needs an inline editor.
 *
 * Keys: Up/Down move, Space toggles the selected channel (or the brief), Enter edits the selected field,
 * T sends a test through the selected channel, L flips between settings and the delivery log, F5 reloads.
 * P pairs Telegram: it shows the bot's link and a one-time code; send the code to the bot, then C checks for it.
 * Secrets (SMTP password, bot token, webhook URL) are NOT here: they live in APIKEYS. The recipient address and
 * Telegram chat id are not readable here either: the table shows a masked hint, and Enter on those rows types a
 * NEW value (empty keeps the stored one).
 */
import { useCallback, useEffect, useState } from "react";
import { fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { deliveryApi } from "../net/deliveryApi";
import type { DeliveryChannel, DeliveryPatch, DeliveryPayload, DeliveryRow, TelegramPairStart } from "../net/types";
import { PanelNote } from "../components/PanelNote";
import { editStart, fieldError, fieldPatch, fieldValue, isRecipientField, type FieldId } from "./dlvrFields";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";

/**
 * One table row. `toggle` is what Space flips; `field` is what Enter edits. A row can have either or both.
 * The brief is split into four rows (enabled, time, days, timezone) so each one has a single obvious key.
 */
interface RowDef {
  id: string;
  label: string;
  channel?: DeliveryChannel;
  toggle?: "brief.enabled" | DeliveryChannel;
  field?: FieldId;
  note?: string;
}
const ROWS: RowDef[] = [
  { id: "email", label: "EMAIL", channel: "email", toggle: "email", field: "email_to" },
  { id: "telegram", label: "TELEGRAM", channel: "telegram", toggle: "telegram", field: "telegram_chat_id" },
  { id: "webhook", label: "WEBHOOK", channel: "webhook", toggle: "webhook", note: "URL: set it in APIKEYS" },
  { id: "desktop", label: "DESKTOP", toggle: "desktop", note: "BROWSER NOTIFICATIONS, ONLY WHILE THIS APP IS OPEN" },
  { id: "brief", label: "BRIEF", toggle: "brief.enabled", note: "DAILY BRIEF SENT TO THE ENABLED CHANNELS" },
  { id: "btime", label: "BRIEF TIME", field: "brief.time" },
  { id: "bdays", label: "BRIEF DAYS", field: "brief.days", note: "mon-fri OR daily" },
  { id: "btz", label: "BRIEF TZ", field: "brief.tz", note: "EMPTY = THIS MACHINE'S TIME ZONE" },
];
const PUSH_TEST: DeliveryChannel[] = ["email", "telegram", "webhook"];

export default function DLVR({ panelId }: FunctionProps) {
  const [data, setData] = useState<DeliveryPayload | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [cur, setCur] = useState(0);
  const [edit, setEdit] = useState<{ row: number; value: string } | null>(null);
  const [msg, setMsg] = useState<{ text: string; cls: "err" | "dim" | "up" | "warn" } | null>(null);
  const [view, setView] = useState<"settings" | "log">("settings");
  const [log, setLog] = useState<DeliveryRow[] | null>(null);
  // A pairing in progress: the bot link and code to show. The chat id never comes here, only `paired: true`.
  const [pair, setPair] = useState<TelegramPairStart | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await deliveryApi.get());
      setLoadErr(null);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    }
  }, []);
  const loadLog = useCallback(async () => {
    try {
      setLog((await deliveryApi.log(100)).deliveries);
    } catch (e) {
      setMsg({ text: `LOG: ${e instanceof Error ? e.message : String(e)}`, cls: "err" });
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  /** Saves a partial change. On success the answer replaces our copy; on failure the error shows inline. */
  const save = useCallback(async (patch: DeliveryPatch) => {
    try {
      const next = await deliveryApi.put(patch);
      setData(next);
      setMsg(null);
      return true;
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : String(e), cls: "err" });
      return false;
    }
  }, []);

  // The key handler is registered once, so it reads the latest state through a ref (see CLAUDE.md: useLatest).
  const latest = useLatest({ data, cur, edit, view, pair });

  // F5 / the Refresh button. Not while the inline editor is open (it has focus and owns its keys, as before).
  usePanelRefresh(panelId, () => {
    if (latest.current.edit) return false;
    void load();
    if (latest.current.view === "log") void loadLog();
  });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { data: d, cur: c, edit: ed, view: v, pair: pr } = latest.current;
        // While the inline editor is open it has focus and handles its own keys.
        if (ed) return false;
        const row = ROWS[c];
        switch (e.key) {
          case "ArrowDown":
          case "j":
            setCur(Math.min(ROWS.length - 1, c + 1));
            return true;
          case "ArrowUp":
          case "k":
            setCur(Math.max(0, c - 1));
            return true;
          case "l":
          case "L":
            setView(v === "log" ? "settings" : "log");
            if (v !== "log") void loadLog();
            return true;
          case " ": {
            if (!d || v !== "settings") return true;
            if (row.toggle === "brief.enabled") {
              void save({ brief: { enabled: !d.settings.brief.enabled } });
            } else if (row.toggle === "desktop") {
              const turningOn = !d.settings.channels.desktop;
              if (!turningOn) {
                void save({ channels: { desktop: false } });
              } else if (typeof Notification === "undefined") {
                setMsg({ text: "NO DESKTOP NOTIFICATIONS IN THIS BROWSER", cls: "err" });
              } else {
                // requestPermission must start inside the keypress; the answer arrives later.
                void Notification.requestPermission().then(
                  (p) => {
                    if (p === "granted") void save({ channels: { desktop: true } });
                    else setMsg({ text: "DESKTOP NOTIFICATIONS BLOCKED BY THE BROWSER", cls: "err" });
                  },
                  () => setMsg({ text: "DESKTOP NOTIFICATIONS BLOCKED BY THE BROWSER", cls: "err" }),
                );
              }
            } else if (row.toggle) {
              void save({ channels: { [row.toggle]: !d.settings.channels[row.toggle] } });
            } else if (row.field === "brief.days") {
              void save({ brief: { days: d.settings.brief.days === "daily" ? "mon-fri" : "daily" } });
            }
            return true;
          }
          case "Enter":
            if (d && v === "settings" && row.field) {
              setMsg(null);
              setEdit({ row: c, value: editStart(d.settings, row.field) });
            }
            return true;
          case "t":
          case "T": {
            if (v !== "settings") return true;
            if (!row.channel || !PUSH_TEST.includes(row.channel)) {
              setMsg({ text: "T TESTS EMAIL, TELEGRAM OR WEBHOOK", cls: "dim" });
              return true;
            }
            const ch = row.channel as Exclude<DeliveryChannel, "desktop">;
            setMsg({ text: `SENDING TEST TO ${ch.toUpperCase()}…`, cls: "dim" });
            deliveryApi.test(ch).then(
              (r) => {
                const text = r.results.map((x) => `${x.channel.toUpperCase()} ${x.status.toUpperCase()}${x.detail ? `: ${x.detail}` : ""}`).join(" · ");
                setMsg({ text: `TEST ${text || "SENT"}`, cls: r.results.every((x) => x.status === "ok" || x.status === "sent") ? "up" : "warn" });
              },
              (err) => setMsg({ text: err instanceof Error ? err.message : String(err), cls: "err" }),
            );
            return true;
          }
          case "p":
          case "P":
            if (v !== "settings") return true;
            setMsg({ text: "ASKING TELEGRAM FOR THE BOT…", cls: "dim" });
            deliveryApi.pairStart().then(
              (r) => {
                setPair(r);
                setMsg(null);
              },
              (err) => setMsg({ text: err instanceof Error ? err.message : String(err), cls: "err" }),
            );
            return true;
          case "c":
          case "C":
            if (v !== "settings" || !pr) return true;
            deliveryApi.pairCheck().then(
              (r) => {
                if (r.paired) {
                  setPair(null);
                  setMsg({ text: "TELEGRAM PAIRED. PRESS SPACE ON THE TELEGRAM ROW TO TURN IT ON, T TO TEST", cls: "up" });
                  void load(); // the row now shows the "chat linked" hint
                } else {
                  setMsg({ text: "CODE NOT SEEN YET: SEND IT TO THE BOT, THEN PRESS C AGAIN", cls: "warn" });
                }
              },
              (err) => {
                setMsg({ text: err instanceof Error ? err.message : String(err), cls: "err" });
                setPair(null); // expired or never started: the shown code is dead
              },
            );
            return true;
          case "Escape":
            if (v === "log") {
              setView("settings");
              return true;
            }
            if (pr) {
              setPair(null); // the code simply expires on the server
              return true;
            }
            return false;
        }
        return false;
      }),
    [panelId, latest, load, loadLog, save],
  );

  /** Enter in the editor: check locally, then save. Esc: drop the edit. */
  const commitEdit = async () => {
    if (!edit) return;
    const field = ROWS[edit.row].field!;
    // Empty on a recipient row means "keep the stored one" (it cannot be read back): nothing to save.
    if (isRecipientField(field) && !edit.value.trim()) {
      setEdit(null);
      return;
    }
    const bad = fieldError(field, edit.value);
    if (bad) {
      setMsg({ text: bad, cls: "err" });
      return;
    }
    if (await save(fieldPatch(field, edit.value) as DeliveryPatch)) setEdit(null);
  };

  if (!data) {
    return loadErr ? (
      <PanelNote kind="error" hint="Press F5 to retry">ERR: {loadErr}</PanelNote>
    ) : (
      <PanelNote kind="loading">LOADING DELIVERY SETTINGS…</PanelNote>
    );
  }
  const s = data.settings;
  const onOff = (r: RowDef): boolean | null =>
    r.toggle === "brief.enabled" ? s.brief.enabled : r.toggle ? s.channels[r.toggle] : null;
  const statusOf = (r: RowDef): string => {
    if (r.channel && r.channel !== "desktop") return data.status[r.channel] ?? "";
    if (r.id === "desktop") return s.channels.desktop ? (typeof Notification !== "undefined" && Notification.permission === "granted" ? "ready" : "NEEDS BROWSER PERMISSION") : "off";
    return "";
  };
  const statusCls = (t: string) => (t.startsWith("KEY REQUIRED") || t.startsWith("NEEDS") ? "warn" : t === "ready" ? "up" : "dim");
  const sel = ROWS[cur];

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">DELIVERY</span> · {view === "log" ? "LOG (NEWEST FIRST)" : "WHERE ALERTS AND THE DAILY BRIEF GO"}
        <span className="dim"> · {view === "log" ? "L/ESC BACK · F5 RELOAD" : "UP/DOWN MOVE · SPACE ON/OFF · ENTER NEW VALUE · T TEST · P PAIR TELEGRAM · L LOG · F5 RELOAD"}</span>
      </div>
      {msg && <div className={msg.cls} data-testid="dlvr-msg">{msg.text}</div>}
      {pair && view === "settings" && (
        <div data-testid="dlvr-pair">
          <span className="acc">PAIR TELEGRAM</span> · OPEN <a href={pair.link} target="_blank" rel="noreferrer">{pair.link}</a> AND SEND{" "}
          <span className="acc" data-testid="dlvr-pair-code">{pair.code}</span>
          <span className="dim"> · VALID {Math.round(pair.expires_in / 60)} MIN · C CHECK · ESC CANCEL</span>
        </div>
      )}
      {view === "settings" ? (
        <table className="t dlvr-t">
          <thead>
            <tr>
              <th>ITEM</th>
              <th>STATE</th>
              <th>STATUS</th>
              <th>VALUE</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r, i) => {
              const on = onOff(r);
              const st = statusOf(r);
              return (
                <tr key={r.id} className={i === cur ? "on" : ""} data-testid={`dlvr-row-${r.id}`}>
                  <td className="acc">{r.label}</td>
                  <td className={on ? "up" : "dim"}>{on == null ? "" : on ? "ON" : "OFF"}</td>
                  <td className={statusCls(st)}>{st}</td>
                  <td>
                    {edit?.row === i ? (
                      <input
                        className="dlvr-in"
                        autoFocus
                        value={edit.value}
                        aria-label={`${r.label} value`}
                        placeholder={isRecipientField(r.field!) ? "NEW VALUE (EMPTY KEEPS THE CURRENT ONE)" : undefined}
                        onChange={(ev) => setEdit({ row: i, value: ev.target.value })}
                        onKeyDown={(ev) => {
                          // Let Ctrl/Alt/Meta chords bubble (Ctrl+K opens the command line); keep plain keys local.
                          if (!ev.ctrlKey && !ev.altKey && !ev.metaKey) ev.stopPropagation();
                          if (ev.key === "Enter") void commitEdit();
                          else if (ev.key === "Escape") {
                            setEdit(null);
                            setMsg(null);
                          }
                        }}
                      />
                    ) : r.field ? (
                      <span>{fieldValue(s, r.field) || <span className="dim">(EMPTY)</span>}</span>
                    ) : (
                      <span className="dim">{r.note ?? ""}</span>
                    )}
                    {r.field && r.note && edit?.row !== i && <span className="dim"> · {r.note}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : log === null ? (
        <PanelNote kind="loading">LOADING DELIVERY LOG…</PanelNote>
      ) : log.length === 0 ? (
        <PanelNote kind="empty" hint="Press T on a channel to send a test">NO DELIVERIES YET</PanelNote>
      ) : (
        <table className="t dlvr-t" data-testid="dlvr-log">
          <thead>
            <tr>
              <th>TIME</th>
              <th>KIND</th>
              <th>REF</th>
              <th>CHANNEL</th>
              <th>STATUS</th>
              <th>DETAIL</th>
            </tr>
          </thead>
          <tbody>
            {log.map((d) => (
              <tr key={d.id}>
                <td className="dim">{fmtTime(d.at * 1000)}</td>
                <td>{d.kind}</td>
                <td className="dim">{d.ref}</td>
                <td className="acc">{d.channel.toUpperCase()}</td>
                <td className={d.status === "ok" || d.status === "sent" ? "up" : "err"}>{d.status.toUpperCase()}</td>
                <td className="dim">{d.detail ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {/* Screen-reader / e2e mirror of the cursor row: the table is plain DOM, but this keeps the same contract as the grids. */}
      <div className="sr" role="status" aria-live="polite">
        {view === "settings" ? `${sel.label} ${onOff(sel) == null ? "" : onOff(sel) ? "ON" : "OFF"} ${statusOf(sel)}`.trim() : `LOG ${log?.length ?? 0} ROWS`}
      </div>
    </div>
  );
}
