# OpenTerm design system

How the screen should look and behave. Read this before changing anything visible. Three people open every screen: the
user, the developer and the agent that edits it next; a change has to serve all three.

## Principles
- **Speed over looks.** No shadows, gradients, transitions or web fonts (bundled font presets excepted, loaded only when chosen). Rounded corners and hover highlights exist only in GUI mode.
- **Colour carries meaning, never decoration.** See the roles below; do not reuse a colour for another job.
- **Never fake data.** A failure says `STALE`, `ERR` or `PROVIDER DOWN` with the source and its age. Test data is labelled.
- **Simple first (GUI mode).** Every panel says what it is in plain words, every button says what it does, and a code always sits next to a plain description. Remove any text or button that only explains the layout or repeats another control.
- **Long lists are grouped.** More than about 8 items gets plain-word sections or a second level (menus open a side flyout); no single list should need scrolling to understand.
- **Keyboard first.** Every action works from the keyboard; the mouse is optional.

## Two modes
- **Terminal mode:** command line, tiled panels, dense 12 px text and 16 px rows, red menu band on each panel.
- **GUI mode** (default for new users): the same app with a menu bar, sidebar, panel toolbars and plain labels. Every GUI rule is scoped to `:root[data-mode="gui"]` in `frontend/src/gui/gui.css`, so Terminal mode never changes by accident.

## Colour roles (GUI, default amber theme)
| Token | Value | Use it for |
|---|---|---|
| `--bg` | `#000000` | the ground |
| `--fg` | `#ffa028` | labels, function codes, the brand |
| `--val` | `#ffffff` | data values and body text |
| `--fg-dim` | `#a8a8a8` | secondary text, descriptions |
| `--up` / `--down` | green / red | price moved up / down. Nothing else |
| `--err` | red | errors only |
| `--sel` | `#1f5fa9` | the selected row, the active choice (range, tab) |
| `--menu` / `--menu-fg` | `#8b1a12` / white | the function band (panel toolbar) |
| `--field` / `--field-fg` | amber / black | anything you type into or pick from (inputs, dropdowns) |
| `--go` / `--go-fg` | green / black | the run key (GO) |
| `--bar` / `--bar-hi` / `--line` | `#1a1a1a` / `#2b2b2b` / `#333333` | window bars, the focused bar, rules |

Themes (`THEME AMBER|GREEN|WHITE|LIGHT`) redefine every token; a new token must get a value in every theme.

## Type and spacing
One monospace family from `--font` (never hard-code a family). GUI: 13 px text, 20 px rows (`--fs`, `--row`). Terminal:
12 px and 16 px. Canvas grids and charts read these variables, so change them in CSS, not in code.

## Screen anatomy (GUI, top to bottom)
1. Tab strip (optional): one tab per panel, the active one amber.
2. Command bar: brand, command line (takes companies, codes and plain-English questions), GO, HELP, market clocks.
3. Menu bar: categories; each dropdown shows plain-word groups that open a side flyout of `CODE  description` rows.
4. Panel title bar: `1  AAPL | GP · Price chart` (number, security, code, plain title).
5. Function band: the panel's buttons on the dark red band, each prefixed with its key (`A) Add`); help, CSV, refresh and close on the right.
6. Quote strip (panels about one security): ticker, name, price, change, open, high, low, volume, source and time.
7. The panel body.

## Adding something visible
- A new function needs a category and subgroup (`functions/categories.ts`) and, if it has buttons, an entry in `gui/toolbars.ts` that presses the panel's own keys.
- A new GUI-only component loads lazily so the startup bundle does not grow.
- Look at it in both modes at 1280 and 1440 px wide before calling it done.
- One text box per screen: the command line. Do not add a second search or symbol box; a bare ticker typed there keeps the panel's current function.
- The function band stays one row. Full width at 1280 px every button shows (5 px side padding, short plain labels: `Price alert`, not `Alert at price`). A narrower panel compacts the band before it would wrap: first the ? / CSV / Refresh / Max / Close buttons go (the title bar's OPTIONS menu has them), then GP's range buttons become one dropdown (`gui/PanelToolbar.tsx`, `data-fit` = the level).
- Flyouts flip to the left when they would run off the right edge of the screen.
- An empty-state note in GUI shows only its first sentence when a hint or button already says the rest (`NO WATCHLISTS.`).
