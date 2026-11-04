# Part 4: Terminal mode conventions

Workflow conventions only (no trade dress, names or assets). All tests: `frontend/e2e/terminal-conventions.spec.ts` (7, Terminal mode),
vitest `command/sectors.test.ts`, `command/sectorKeys.test.ts`, `keys/numberSelect.test.ts`, `functions/FUNC.test.ts`.

## 1. Sector words (`command/sectors.ts`, used by `command/parser.ts`)
`<SECURITY> [MARKET] [SECTOR] [FUNCTION] [args]`. Words (case-insensitive): EQUITY/EQ, INDEX/IDX, CURNCY/CCY, COMDTY/CMD, GOVT/GOV, CORP, CRYPTO.
A word that is also a function code (FX, CMDTY, CRYP) is NOT a sector word: the function wins.
`SPX INDEX` -> ^GSPC, `EURUSD CURNCY` -> EURUSD=X, `CL1 COMDTY` -> CL=F (`CO1` -> BZ=F), `AAPL US EQUITY` -> AAPL (market suffix kept),
`US10Y GOVT` -> ^TNX (US3M/5Y/10Y/30Y only; other GOVT = clear error), `CORP` = clear error (no free data). Behaviour change: CORP and
unknown GOVT used to be silently ignored, now they say why. `ASSET_CLASS` was removed from `markets.ts`.

## 2. Number-select (`keys/numberSelect.ts`, wired in `App.tsx`)
In a panel with a canvas grid, a digit no panel handled starts a row number (1-3 digits, 3 s window, status line shows `ROW n`);
Enter replays Home + (n-1) x ArrowDown + Enter on the panel, so it equals moving the cursor and pressing Enter. Row beyond the end:
`NO ROW n (m ROWS)`. `:` hands the digits to the command line (`3:GP` still targets panel 3); Esc/Backspace/other keys cancel.
Panels that bind digits themselves (BT 1-4, GP, MOV tabs 1-5 ...) get the key first, so they are skipped automatically.
DOM lists (no `.grid`) and FUNC letters-only filter: digits work in FUNC, not in DOM lists. `Grid` now carries `data-rows`.

## 3. Function keys (`keys/keybindings.json`, labels in `keys/keys.ts`, `command/sectorKeys.ts`)
F2 EQUITY, F3 INDEX, F4 CURNCY, F8 COMDTY, F9 GOVT, Shift+F9 CORP. They write/replace the sector word after the security (before the
function) and work from the command line (F-keys no longer wait for the line to lose focus). Empty line uses the panel's security.
Back key: Alt+Backspace added to `historyBack` (previous panel view; Ctrl+[ stays). Left unbound on purpose: F1 (browser help), F5 stays refresh,
F6 (address bar), F7 (caret browsing), F10 (menu), F11 (fullscreen, already refused by SETTINGS KEYS), F12 (devtools; can be bound by hand in SETTINGS KEYS).
All rebindable through SETTINGS KEYS (actions `sectorEquity ... sectorCorp`).

## 4. FUNC directory (`functions/FUNC.tsx`, `funcDirectory.ts`)
Every function plus aliases, sorted; columns CODE / PURPOSE (first clause of the title) / TAKES (SEC) / GUI MENU. Letters filter (code prefix first),
arrows move, Enter runs `execute(code)`, Backspace/Esc clear. Lazy chunk 1.3 KB gz; category Settings. Reachable as `MENU` and `DIR`.

## 5. Aliases (`functions/aliases.ts`, resolved in `registry.ts` + `execute.ts`)
Added: WCRS->FXC (cross rates), MOST->MOV (most active), PRTU->PORT, MENU/DIR->FUNC. Our codes already follow common mnemonics (GP DES FA HDS OMON ...),
so no canonical code was renamed: renaming would touch ~200 specs and risk saved layouts. An alias shares the canonical definition (`FUNCTIONS.get(alias).code`
is canonical) and `execute` rewrites it, so panels and saved layouts only ever hold canonical codes; old layouts are untouched. Rejected: HP (a real ticker,
function codes win over tickers), GC (futures ticker).

## Left over
- Entry bundle grew about 1.6 KB gz (sector tables 0.8, number-select 0.5, sector keys 0.4); budget was 1.5. Trim `INDEXES` in `sectors.ts` if it matters.
- Number-select only covers canvas grids; DOM tables/lists (CORR, LAYOUT index) not covered.
- `docs/FUNCTIONS.md` regenerated (FUNC row, sector key rows); aliases are not listed there, only in FUNC.
