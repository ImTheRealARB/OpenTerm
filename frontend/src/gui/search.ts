/**
 * Pure helpers for the GUI shell (no React, no store imports, so vitest can test them).
 * The symbol picker ends up running ordinary command-line text; this helper only decides WHICH text to run.
 */
/**
 * What to run when Enter is pressed in the symbol picker. A bare ticker keeps the panel's current function when
 * that function works on a security (a GP chart of MSFT becomes a GP chart of AAPL), otherwise it is the plain
 * command-line form `AAPL`, which opens DES. Typed text with spaces is passed through as typed ("RELIANCE IN GP").
 */
export function symbolCommand(
  text: string,
  ctx: { currentFn?: string; isFunction: (code: string) => boolean; needsSecurity: (code: string) => boolean },
): string | null {
  const t = text.trim();
  if (!t) return null;
  if (/\s/.test(t) || ctx.isFunction(t.toUpperCase())) return t;
  return ctx.currentFn && ctx.needsSecurity(ctx.currentFn) ? `${t} ${ctx.currentFn}` : t;
}
