/**
 * Pure helpers for the DLVR and BRIEF panels (no DOM, no network, so vitest can test them).
 * The field checks mirror backend/openterm/delivery/settings.py. The backend stays the judge (it answers 400 with a
 * message); checking here too just saves a round trip and gives the error the moment Enter is pressed.
 */
import type { BriefSection, DeliverySettings } from "../net/types";

const EMAIL_RE = /^[^@\s,;<>]{1,64}@[^@\s,;<>]{1,255}$/;
const CHAT_RE = /^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$/;
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
export const DAYS = ["mon-fri", "daily"] as const;

/** The editable fields of the settings document. */
export type FieldId = "email_to" | "telegram_chat_id" | "brief.time" | "brief.days" | "brief.tz";

/** Returns an error text, or null when `value` is acceptable for the field. An empty email / chat id means "keep the stored one". */
export function fieldError(field: FieldId, value: string): string | null {
  const v = value.trim();
  switch (field) {
    case "email_to":
      return v && !EMAIL_RE.test(v) ? "EMAIL MUST BE ONE ADDRESS" : null;
    case "telegram_chat_id":
      return v && !CHAT_RE.test(v) ? "CHAT ID MUST BE A NUMBER OR @channelname" : null;
    case "brief.time":
      return TIME_RE.test(v) ? null : "TIME MUST BE HH:MM (24 HOUR)";
    case "brief.days":
      return (DAYS as readonly string[]).includes(v) ? null : "DAYS MUST BE mon-fri OR daily";
    case "brief.tz":
      // Empty = the machine's own zone. A real zone name is checked by the backend (it knows the zone database).
      return null;
  }
}

/** The PUT body for one field edit. */
export function fieldPatch(field: FieldId, value: string): Record<string, unknown> {
  const v = value.trim();
  if (field === "email_to" || field === "telegram_chat_id") return { [field]: v };
  return { brief: { [field.slice("brief.".length)]: v } };
}

/**
 * What the table shows for a field. The recipient address and chat id never reach the browser, so for those two this is
 * the masked hint ("a•••@gmail.com", "chat linked") or "" when nothing is set. Use `editStart` for the editor's text.
 */
export function fieldValue(s: DeliverySettings, field: FieldId): string {
  if (field === "email_to") return s.recipients.email.hint;
  if (field === "telegram_chat_id") return s.recipients.telegram.hint;
  return s.brief[field.slice("brief.".length) as "time" | "days" | "tz"];
}

/** True for the two write-only fields (stored value never readable here). */
export const isRecipientField = (field: FieldId): boolean => field === "email_to" || field === "telegram_chat_id";

/** The text the inline editor opens with: empty for a recipient (it cannot be read back), the current value otherwise. */
export function editStart(s: DeliverySettings, field: FieldId): string {
  return isRecipientField(field) ? "" : fieldValue(s, field);
}

/** The line under a BRIEF section title: `source · age`, or STALE, or the error text. */
export function sectionMeta(s: BriefSection, fmtAge: (sec: number) => string): { text: string; cls: "err" | "warn" | "dim" } {
  if (s.error) return { text: `ERR: ${s.error}`, cls: "err" };
  const src = (s.source ?? "n/a").toUpperCase();
  const age = s.age_s == null ? "" : ` · ${fmtAge(s.age_s)}`;
  return s.stale ? { text: `STALE · ${src}${age}`, cls: "warn" } : { text: `${src}${age}`, cls: "dim" };
}

/** "2026-11-03 08:30" in the browser's zone, from epoch seconds. */
export function briefStamp(epochSec: number): string {
  const d = new Date(epochSec * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
