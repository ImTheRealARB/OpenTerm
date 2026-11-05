/**
 * Pure helper for `execute()` (no store imports, so vitest can test it).
 *
 * A command that names a security but no function ("MSFT") has to pick a function to open.
 *   - Terminal mode always opens DES (the company description): that is the documented command-line behaviour.
 *   - GUI mode passes `keepFn`: if the panel is already showing a function that works on a security (a GP chart),
 *     keep that function, so typing MSFT turns a chart of AAPL into a chart of MSFT instead of jumping to DES.
 * `currentFn` is the target panel's function right now (undefined for a brand-new empty panel) and `needsSecurity` says
 * whether a function code takes a security (HELP, N or WL do not, so a ticker typed over those still opens DES).
 */
export function bareSecurityFn(
  keepFn: boolean | undefined,
  currentFn: string | undefined,
  needsSecurity: (code: string) => boolean,
): string {
  return keepFn && currentFn && needsSecurity(currentFn) ? currentFn : "DES";
}
