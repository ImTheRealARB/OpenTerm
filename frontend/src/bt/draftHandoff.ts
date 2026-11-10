/**
 * Hands an AI-drafted strategy to `BT EDIT <name>` (pure, in memory only: nothing is saved, nothing leaves the browser).
 * The editor takes the draft once when it opens that name and shows it as unsaved text; the user saves with Ctrl+S as usual.
 */
let pending: { name: string; code: string } | null = null;

export function setPendingDraft(name: string, code: string): void {
  pending = { name, code };
}

/** The draft for this strategy name, once (it is cleared when taken); a draft for another name stays pending. */
export function takePendingDraft(name: string): string | null {
  if (!pending || pending.name !== name) return null;
  const code = pending.code;
  pending = null;
  return code;
}
