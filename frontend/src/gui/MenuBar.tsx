import { useEffect, useMemo, useRef, useState } from "react";
import { FUNCTION_LIST } from "../functions/registry";
import { CATEGORIES, SUB_HELP, SUB_LOOK, menuOf, type Category } from "../functions/categories";
import { FONT_PRESETS, findPreset } from "../settings/fontPresets";
import { setMode, settingsStore, updateSettings } from "../settings/runtime";
import { useStore } from "../state/store";
import { chromeKeyDown, focusCommandLine, moveFocus } from "./chrome";
import { Flyout } from "./Flyout";
import { runCommand } from "./run";
import { showWelcome, startTour } from "./onboarding";
import { toggleSidebar, useSidebarHidden } from "./sidebarState";
import { toggleStatusBar, useStatusBarShown } from "./statusBarState";
import { setTabs, useTabsOn } from "./tabsState";
import { TEMPLATE_INFO } from "./templateMenu";
import { shortTitle } from "./titleText";

/** One row of a menu: a function, or one of the extra GUI rows under Settings (status bar, font, switch mode, tour, welcome card). */
type Entry =
  | { kind: "fn"; code: string; title: string; built: boolean; run?: string }
  | { kind: "status" }
  | { kind: "font" }
  | { kind: "terminal" }
  | { kind: "tour" }
  | { kind: "welcome" };

/** A group's rows: its functions, then the GUI-only rows that belong with them (keyed by the subgroup names in categories.ts). */
function extrasFor(group: string): Entry[] {
  if (group === SUB_HELP) return [{ kind: "tour" }, { kind: "welcome" }];
  if (group === SUB_LOOK) return [...TEMPLATE_INFO.map((t) => ({ kind: "fn" as const, code: "TMPL", title: "Template: " + t.label, built: true, run: "TMPL " + t.id })), { kind: "status" }, { kind: "font" }, { kind: "terminal" }];
  return [];
}

/** The subgroup whose flyout is open, and the row it hangs from (the flyout is placed beside that row). */
type OpenSub = { name: string; row: HTMLElement };

/**
 * GUI menu bar: the seven categories. A short category (Charts, News, Portfolio, Backtest) opens a dropdown of its functions;
 * a long one (Markets, Research, Settings) opens a dropdown of plain-word groups ("Crypto", "Options"), and each group opens a
 * side flyout with its functions (`categories.ts` says what goes where). There is no text box here: the command line above
 * already takes companies, codes and questions, and one place to type is easier than two.
 *
 * Mouse: click a category to open it, hover another while one is open to switch. Hover (or click) a group to open its flyout;
 * click a function to run it.
 * Keyboard: Tab reaches the categories; Enter / Space / ArrowDown open one and focus its first row. In a dropdown, ArrowUp /
 * ArrowDown move, ArrowRight on a group opens its flyout (focus moves into it), ArrowRight / ArrowLeft elsewhere move to the
 * next / previous category. In a flyout, ArrowUp / ArrowDown move, ArrowLeft or Esc close it and return to the group row.
 * Esc in a dropdown closes it and returns focus to the command line. Picking a function runs it in the focused panel
 * through `runCommand` (= the command line's `execute`).
 */
export function MenuBar() {
  const [open, setOpen] = useState<Category | null>(null);
  const [sub, setSub] = useState<OpenSub | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  // Set when a menu or flyout was opened from the keyboard, so the effects below move focus into it (a mouse open must not steal focus).
  const focusOnOpen = useRef(false);
  const focusOnSub = useRef(false);
  // category -> its groups and their functions (fixed for the session: the registry does not change while the app runs).
  const menus = useMemo(() => new Map(CATEGORIES.map((c) => [c, menuOf(c, FUNCTION_LIST)] as const)), []);
  const sidebarHidden = useSidebarHidden();
  const statusShown = useStatusBarShown();
  // A stored name that matches a preset ("JetBrains Mono", "geist mono") selects that preset; anything else is a custom font.
  const font = useStore(settingsStore, (s) => findPreset(s.font)?.name ?? s.font);
  const tabsOn = useTabsOn();

  const entries = (c: Category, group: string): Entry[] => [
    ...(menus.get(c)!.find((g) => g.name === group)?.items ?? []).map((f): Entry => ({ kind: "fn", code: f.code, title: shortTitle(f.title), built: !!f.load })),
    ...extrasFor(group),
  ];

  // A different category (or none) closes any open flyout.
  useEffect(() => {
    setSub(null);
  }, [open]);

  // Move focus into a keyboard-opened dropdown, then into a keyboard-opened flyout.
  useEffect(() => {
    if (open && focusOnOpen.current) bar.current?.querySelector<HTMLElement>(".gm-drop .gm-item")?.focus();
    focusOnOpen.current = false;
  }, [open]);
  useEffect(() => {
    if (sub && focusOnSub.current) bar.current?.querySelector<HTMLElement>(".gm-fly .gm-item")?.focus();
    focusOnSub.current = false;
  }, [sub]);

  // Click anywhere outside the bar closes an open menu (the flyout is inside the bar's DOM, so clicks there count as inside).
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!bar.current?.contains(e.target as Node)) setOpen(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  const pick = (e: Entry) => {
    setOpen(null);
    if (e.kind === "status") toggleStatusBar();
    else if (e.kind === "font") return; // the font row is a <select>; it changes the font itself
    else if (e.kind === "terminal") {
      setMode("terminal");
      focusCommandLine();
    } else if (e.kind === "tour") startTour();
    else if (e.kind === "welcome") showWelcome();
    else runCommand(e.run ?? e.code);
  };

  /** Opens the next / previous category's menu and focuses its first row (ArrowRight / ArrowLeft from inside a menu). */
  const stepCategory = (dir: 1 | -1) => {
    const cats = Array.from(bar.current!.querySelectorAll<HTMLElement>(".gm-cat"));
    const next = cats[(CATEGORIES.indexOf(open!) + dir + cats.length) % cats.length];
    focusOnOpen.current = true;
    setOpen(next.dataset.cat as Category);
    next.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return; // chords bubble (chromeKeyDown would also ignore them)
    const el = e.target as HTMLElement;
    const fly = el.closest<HTMLElement>(".gm-fly");
    const drop = el.closest<HTMLElement>(".gm-drop");
    const onCategory = el.classList.contains("gm-cat");
    const onItem = el.classList.contains("gm-item");
    if (fly && sub && (e.key === "Escape" || e.key === "ArrowLeft")) {
      // Close only the flyout and go back to its group row (Esc must not also close the dropdown or leave the menu).
      e.preventDefault();
      e.stopPropagation();
      const row = sub.row;
      setSub(null);
      row.focus();
      return;
    }
    if (e.key === "Escape") setOpen(null);
    else if (onCategory && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      focusOnOpen.current = true;
      setOpen(el.dataset.cat as Category);
    } else if (onCategory && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
      e.preventDefault();
      moveFocus(bar.current!, ".gm-cat", e.key === "ArrowRight" ? 1 : -1);
      // With a menu open, the new category's menu opens too (like a desktop menu bar).
      if (open) setOpen((document.activeElement as HTMLElement).dataset.cat as Category);
    } else if (onItem && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      // Inside a flyout move among its rows; in a dropdown only among the dropdown's own rows (not the flyout's).
      if (fly) moveFocus(fly, ".gm-item", e.key === "ArrowDown" ? 1 : -1);
      else if (drop) moveFocus(drop, ":scope > .gm-item", e.key === "ArrowDown" ? 1 : -1);
    } else if (onItem && e.key === "ArrowRight" && el.dataset.group) {
      e.preventDefault();
      focusOnSub.current = true;
      setSub({ name: el.dataset.group, row: el });
    } else if (onItem && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
      e.preventDefault();
      stepCategory(e.key === "ArrowRight" ? 1 : -1);
    } else if (onItem && (e.key === "Home" || e.key === "End")) {
      e.preventDefault();
      const items = (fly ?? drop)!.querySelectorAll<HTMLElement>(fly ? ".gm-item" : ":scope > .gm-item");
      items[e.key === "Home" ? 0 : items.length - 1]?.focus();
    }
    chromeKeyDown(e);
  };

  const row = (en: Entry) =>
    en.kind === "font" ? (
      // One-click font switch (silent): bundled presets load on first use; any other installed font via SETTINGS FONT <name>.
      <div key="font" className="gm-fontrow" role="none">
        <span className="gm-code">FONT</span>
        <select
          className="gm-item gm-font"
          data-testid="font-select"
          aria-label="Font"
          title="Any installed font: SETTINGS FONT name"
          value={font}
          onChange={(e) => {
            const v = e.target.value;
            setOpen(null);
            updateSettings((s) => ({ ...s, font: v }));
            focusCommandLine();
          }}
        >
          {FONT_PRESETS.map((p) => (
            <option key={p.name} value={p.name}>{p.label}</option>
          ))}
          {!findPreset(font) && <option value={font}>{font}</option>}
        </select>
      </div>
    ) : en.kind === "status" ? (
      <button key="status" type="button" role="menuitemcheckbox" aria-checked={statusShown} className="gm-item" data-testid="statusbar-toggle" onClick={() => pick(en)}>
        <span className="gm-code">VIEW</span>
        <span>Bottom status bar: {statusShown ? "shown" : "hidden"}</span>
      </button>
    ) : en.kind !== "fn" ? (
      <button key={en.kind} type="button" role="menuitem" className={"gm-item" + (en.kind === "terminal" ? " gm-sep" : "")} onClick={() => pick(en)}>
        <span className="gm-code">{en.kind === "terminal" ? "MODE" : "HELP"}</span>
        <span>{en.kind === "terminal" ? "Switch to Terminal mode" : en.kind === "tour" ? "Take the tour" : "Show welcome card"}</span>
      </button>
    ) : (
      <button key={en.run ?? en.code} type="button" role="menuitem" className={"gm-item" + (en.built ? "" : " dim")} data-template={en.run?.slice(5)} onClick={() => pick(en)}>
        <span className="gm-code">{en.code}</span>
        <span>{en.title}</span>
      </button>
    );

  return (
    <div className="gm-bar" ref={bar} role="menubar" data-testid="gui-menubar" onKeyDown={onKeyDown}>
      {/* Shows or hides the left sidebar (the menu bar above already reaches every function). */}
      <button type="button" className="gm-side" data-testid="sidebar-toggle" aria-pressed={!sidebarHidden} title="Show or hide the sidebar" onClick={toggleSidebar}>
        {sidebarHidden ? "▸" : "◂"} Sidebar
      </button>
      {/* Panels as browser-style tabs (one at a time) or tiles (side by side). */}
      <button type="button" className="gm-side" data-testid="layout-toggle" title={tabsOn ? "Show the open panels side by side" : "Show the open panels as tabs"} onClick={() => setTabs(!tabsOn)}>
        {tabsOn ? "Tiles" : "Tabs"}
      </button>
      {/* The sidebar and the category menus are two ways to reach the same functions: show one or the other. */}
      {sidebarHidden && CATEGORIES.map((c) => {
        const groups = menus.get(c)!;
        const twoLevel = groups.length > 1; // one group = short enough to list its functions directly
        return (
          <div key={c} className="gm-slot">
            <button
              type="button"
              role="menuitem"
              aria-haspopup="menu"
              aria-expanded={open === c}
              className={"gm-cat" + (open === c ? " on" : "")}
              data-cat={c}
              onClick={(e) => {
                // detail === 0 means the click came from Enter / Space, not a mouse: then focus the first row.
                focusOnOpen.current = e.detail === 0 && open !== c;
                setOpen(open === c ? null : c);
              }}
              onMouseEnter={() => open && setOpen(c)}
            >
              {c}
            </button>
            {open === c && (
              <div className={"gm-drop" + (twoLevel ? " gm-groups" : "")} role="menu" aria-label={c}>
                {twoLevel
                  ? groups.map((g) => (
                      <button
                        key={g.name}
                        type="button"
                        role="menuitem"
                        aria-haspopup="menu"
                        aria-expanded={sub?.name === g.name}
                        className={"gm-item gm-sub" + (sub?.name === g.name ? " on" : "")}
                        data-group={g.name}
                        // Hover opens the group (a desktop menu); a click does too, for touch screens and keyboard users.
                        onMouseEnter={(e) => sub?.name !== g.name && setSub({ name: g.name, row: e.currentTarget })}
                        onClick={(e) => {
                          focusOnSub.current = e.detail === 0;
                          setSub({ name: g.name, row: e.currentTarget });
                        }}
                      >
                        <span>{g.name}</span>
                        <span className="gm-arrow" aria-hidden="true">›</span>
                      </button>
                    ))
                  : entries(c, groups[0].name).map(row)}
                {twoLevel && sub && (
                  <Flyout key={sub.name} anchor={sub.row} label={sub.name} testId="gm-flyout">
                    {entries(c, sub.name).map(row)}
                  </Flyout>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
