# Build 1B-B: beginner tasks 3, 6, 7, 8 and items 2-6

All ten beginner tasks now pass (`frontend/e2e/beginner.spec.ts`, markers deleted, one extra test for the starter layout).

## What changed
1. **Tasks 3, 6, 7, 8.**
   - `gui/askBus.ts`: a panel's empty state opens its toolbar's ask box (`requestAsk(panelId, "Add")`); `PanelToolbar` listens.
   - `gui/toolbars.ts`: new `DES` ("Set alert", `ALRT {symbol} > {input}`) and `ALRT` ("Add an alert") entries, `{symbol}` token, `splitCommas` (PORT Add runs one `PORT MAIN ADD ...` per comma-separated entry), `askCommands`, `askButton`. `Panel.tsx` passes the panel's security to the toolbar.
   - WL / PORT / ALRT empty states carry "Add a stock" / "Add an alert" actions (index views: "Start my watchlist" / "Start my portfolio"). A missing list was already an empty note.
   - PORT summary says `MKT VALUE` in GUI (Terminal keeps `MKT VAL`).
   - BT: `functions/BtStarter.tsx` (GUI only) lists `/api/bt/templates` as `bt-template` buttons (plain summary, technical name grey), stock box (AAPL), "Run backtest" posts `code` to `/api/bt/run`; BT got a shared `post()` helper.
2. **Starter layout.** `gui/starterLayout.ts`: Q of 6 large US stocks, GP SPY, N TOP; applied once from `GuiOverlays` (dynamic import) only when nothing is saved (no `openterm.workspace`) and the workspace is the untouched HELP panel. Real providers, no fake data. Terminal and saved layouts untouched.
3. **KEY REQUIRED.** `KeyRequiredLine.tsx` exports `KeyNeeded` (GUI: PanelNote + "Open API keys" button; Terminal: unchanged amber line). Wired into DES, N, GP (they keep the ApiError for it), KITE and ResearchPanel's own text.
4. **BT editor** fills the panel in GUI (`gui.css`, `.editor-host`); Terminal keeps 22em.
5. **Tour and help.** Tour text uses `{toggleMode}` / `{helpDrawer}` filled by `tourText(step, effectiveBindings())`. Help drawer: purpose sentence (`gui/purposes.ts`, falls back to the registry title), then Buttons, then Keys (live bindings for refresh, CSV, window menu, help), the typed form last and small.
6. **FA table** (GUI only): `--grid-hdr-*`, `--grid-row-rule`, `--grid-col-rule` set on `:root[data-mode="gui"] .fa`; the canvas Grid re-reads them.

## Tests
tsc clean; vitest 539 + new (toolbars, starterLayout, purposes, tourSteps) pass; full Playwright run: 237/238, the one failure (polish-analysis expected `MKT VAL`) fixed and rerun green with beginner, phase8, gui-shell. `docs/FUNCTIONS.md` unchanged (no registry/keybinding change).

## Bundle (gzip -9 of the entry JS, `npx vite build`)
119,276 -> 120,585 B (+1.3 KB, includes whatever the concurrent agent added); cap 122,900. Entry CSS 4.82 KB. BtStarter lives in the BT chunk; starterLayout is a lazy chunk.

## Left over
- No e2e for KEY REQUIRED in GUI (unit-level only through types); no screenshot review of the FA restyle or the starter layout yet (1C).
- `PanelNote` Retry is still only wired in DES.
- BT starter runs `code` templates with fixed 1D / 5Y; "Run again" (R) on such a run is untested.
