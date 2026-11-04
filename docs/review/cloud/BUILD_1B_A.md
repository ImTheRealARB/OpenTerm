# Build 1B-A: beginner tasks 1, 2, 4, 5, 9, 10

Tests 1, 2, 4, 5, 9, 10 in `frontend/e2e/beginner.spec.ts` now pass (their `test.fail()` markers are gone). 3, 6, 7, 8 stay marked for the next agent.

## What changed
- **Company-name search.** `gui/SymbolPicker.tsx` is now a combobox with a `role="listbox"` of options ("AAPL Apple Inc."): arrows move, Enter runs the highlighted one (or, for a name like "apple", the top match; a ticker or spaced text is run as typed), click works, Esc closes the list first.
  - Pure matcher: `gui/companySearch.ts` (`matchCompanies`, `closestCompanies`, `enterTarget`, `cleanName`). The brief said `gui/search.ts`; it is a separate file so the sidebar helpers stay small. Tests: `companySearch.test.ts`.
  - Data: `gui/suggestData.ts` (dynamic `import()`, first focus/typing only): screener universe via `api9.screener()` plus Yahoo name search `api.search` (`/api/search`) when fewer than 3 local matches. `/api/resolve` is only an alias map (BTC -> BTC-USD), so it is not used. Hook: `gui/useCompanies.ts` (120 ms debounce).
  - Sidebar search shows up to 4 matching companies above the function hits (`.gs-company`).
- **Sidebar "Start here"** (`data-testid="start-here"`, class `gs-start`, not `.gs-head`): Stock chart (GP), My watchlist (WL MY-STOCKS), Top news (N TOP), World markets (WEI), My portfolio (PORT MAIN), Try a backtest (BT). Code small and grey beside the name. All 7 categories now start collapsed.
- **Glossary.** `gui/glossary.ts` (37 terms), `gui/glossaryTip.ts` (one delegated listener on document, hover + focusin, `role="tooltip"`, GUI mode only, installed lazily from `Overlays.tsx`), `gui/term.ts` (`termProps(term, gui)` adds `tabIndex=0` in GUI mode). DES labels carry `data-term` (MKT CAP, P/E, EPS, DIV YIELD, BETA, P/BOOK, SHARES OUT, FLOAT, AVG VOLUME, DAY RANGE, 52W RANGE). Vitest `glossary.test.ts` scans `functions/`, `gui/`, `components/` `.tsx` for terms and checks each has an entry.
- **Errors with a next step.** `components/PanelNote.tsx` gets `plain`, `actions`, `onRetry` (GUI only; buttons `data-testid="note-action"`), plus an automatic plain line for error/stale (`plainLine`, tested). DES: unknown symbol keeps the exact `QUOTE:/PROFILE: NO DATA` lines and adds "There is no stock called X." with "Try AAPL" style buttons (closest names, else the biggest companies); other DES load failures get a plain line and a Retry.
- Spec: unmocked `/api/search` is now mocked (empty); test 10 uses `note.first()` for the visibility check.

## Bundle (gzip -9, `npx vite build`)
Entry JS 117,867 -> 119,276 B (+1.4 KB); entry CSS 4.28 -> 4.55 KB. Lazy chunks: `suggestData` 0.42 KB, `glossaryTip` + glossary 2.4 KB. Within the 2.5 KB share.

## Left / notes
- Canvas grid column headers have no `data-term` (canvas is not DOM); only DES labels do.
- `PanelNote` Retry exists only where a panel passes `onRetry` (DES only so far); most other panels have no wiring yet.
- Tasks 3, 6, 7, 8 are for the other agent: they can reuse `PanelNote` `actions` for empty-state buttons.
