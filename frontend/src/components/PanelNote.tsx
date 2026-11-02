import type { ReactNode } from "react";

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
 */
export type NoteKind = "loading" | "empty" | "error" | "stale";

export function PanelNote({ kind, children, hint }: { kind: NoteKind; children: ReactNode; hint?: ReactNode }) {
  return (
    // role=status lets screen readers announce the change; data-kind lets e2e tests assert the state without
    // depending on the wording.
    <div className={`pnote pnote-${kind}`} role="status" data-kind={kind}>
      <div className="pnote-msg">{children}</div>
      {hint != null && <div className="pnote-hint">{hint}</div>}
    </div>
  );
}
