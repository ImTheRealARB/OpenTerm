import type { ReactNode } from "react";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";

/**
 * One consistent look for a panel that has no rows to show yet (both modes).
 *
 *   loading  waiting for the first answer          "LOADING AAPL 1Y…"
 *   empty    the answer came back with nothing     "NO HEADLINES"  + a hint saying what to do next
 *   error    the request failed                    "ERR: …"        (keep the source and age in the text: never fake data)
 *   stale    data shown is old                     "STALE: …"
 *
 * `hint` is the next step for the user, e.g. "Add one: WL ADD AAPL" or "Press F5 to retry". It is plain text
 * so it reads the same in Terminal and GUI mode. Rendering only: it fetches nothing and holds no state.
 *
 * GUI mode only (Terminal output is unchanged): an error / stale note also gets
 *   - one plain-English line under the exact message (`plain` overrides the automatic one), and
 *   - buttons: `actions` (e.g. "Try AAPL") and, when the panel passes `onRetry`, a "Retry" button.
 * The exact error text, source and age always stay as given.
 */
export type NoteKind = "loading" | "empty" | "error" | "stale";

export interface NoteAction {
  label: string;
  onClick: () => void;
}

/** Text of a message that is made of strings only (anything with elements gives ""). */
function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  return "";
}

/**
 * One plain sentence for an ERR / STALE note, from its exact text. Pure, and deliberately general: it names the
 * source when the text does, and says whether the app will try again by itself.
 */
export function plainLine(kind: NoteKind, text: string): string | null {
  if (kind !== "error" && kind !== "stale") return null;
  const t = text.toUpperCase();
  if (t.includes("KEY REQUIRED")) return "This needs a free API key. Open API keys to add one; everything else works without it.";
  if (t.includes("NO DATA") || t.includes("NOT FOUND")) return "The data source returned nothing for that. It may not carry it, or there is a gap right now: press Retry, or try another name or range.";
  const source = /\b(YAHOO|NASDAQ|SEC|FRED|COINGECKO|BINANCE|GDELT|TREASURY|BLS|BEA|STOOQ|OPENROUTER)\w*/i.exec(text)?.[0];
  const who = source ? source[0].toUpperCase() + source.slice(1).toLowerCase() : "The data source";
  const age = /(\d+\s*(?:s|sec|m|min|h|hr|d)\b)\s*OLD/i.exec(text)?.[1];
  if (kind === "stale") return `${who} is slow to answer. ${age ? `Data shown is ${age} old. ` : "Data shown is out of date. "}It retries on its own.`;
  return `${who} isn't answering right now. ${age ? `Data shown is ${age} old. ` : ""}It retries on its own.`;
}

export function PanelNote({
  kind,
  children,
  hint,
  plain,
  actions,
  onRetry,
}: {
  kind: NoteKind;
  children: ReactNode;
  hint?: ReactNode;
  plain?: ReactNode;
  actions?: NoteAction[];
  onRetry?: () => void;
}) {
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const line = gui ? (plain ?? plainLine(kind, textOf(children))) : null;
  const buttons: NoteAction[] = gui ? [...(actions ?? []), ...(onRetry && (kind === "error" || kind === "stale") ? [{ label: "Retry", onClick: onRetry }] : [])] : [];
  return (
    // role=status lets screen readers announce the change; data-kind lets e2e tests assert the state without
    // depending on the wording.
    <div className={`pnote pnote-${kind}`} role="status" data-kind={kind}>
      <div className="pnote-msg">{children}</div>
      {hint != null && <div className="pnote-hint">{hint}</div>}
      {line && <div className="pnote-plain">{line}</div>}
      {buttons.length > 0 && (
        <div className="pnote-actions">
          {buttons.map((a) => (
            <button key={a.label} type="button" data-testid="note-action" onClick={a.onClick}>
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
