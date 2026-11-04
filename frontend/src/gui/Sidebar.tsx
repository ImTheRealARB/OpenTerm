import { useMemo, useRef, useState } from "react";
import { FUNCTION_LIST, isFunction } from "../functions/registry";
import { CATEGORIES, categoryOf, groupByCategory, type Category } from "../functions/categories";
import { chromeKeyDown, moveFocus } from "./chrome";
import { runCommand, runSymbol, runTyped } from "./run";
import { searchFunctions, sidebarEnter } from "./search";
import { useCompanies } from "./useCompanies";

type Def = (typeof FUNCTION_LIST)[number];

/** Groups open when the sidebar first shows; the rest start collapsed so the list is not 100 rows long. */
const OPEN_AT_START: readonly Category[] = [];

/**
 * "Start here": the everyday tasks in plain words, each one click. `text` is ordinary command-line text (run by
 * `runCommand`, like every GUI control); `code` is shown small and grey as a learning aid, never on its own.
 *  - "Stock chart" runs GP on the panel's current security (the "sticky" one from your last lookup).
 *  - "Top news" is `N TOP`, explicit, because a bare `N` after a stock lookup shows THAT stock's news.
 *  - The watchlist and portfolio get default names so the first click needs no typing.
 */
const START_HERE: readonly { label: string; code: string; text: string }[] = [
  { label: "Stock chart", code: "GP", text: "GP" },
  { label: "My watchlist", code: "WL", text: "WL MY-STOCKS" },
  { label: "Top news", code: "N", text: "N TOP" },
  { label: "World markets", code: "WEI", text: "WEI" },
  { label: "My portfolio", code: "PORT", text: "PORT MAIN" },
  { label: "Try a backtest", code: "BT", text: "BT" },
];

/**
 * GUI sidebar: every registered function grouped by category, with a search box that does the same job as the
 * command line. Typing filters the list (code or title); Enter runs the typed command, or the top match for a loose
 * word (see `sidebarEnter`). Clicking a row runs that function in the focused panel. Groups collapse and expand.
 */
export function Sidebar() {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<ReadonlySet<Category>>(() => new Set(CATEGORIES.filter((c) => !OPEN_AT_START.includes(c))));
  const root = useRef<HTMLElement>(null);
  const groups = useMemo(() => groupByCategory(FUNCTION_LIST), []);
  const matches = useMemo(() => searchFunctions(query, FUNCTION_LIST), [query]);
  const searching = query.trim() !== "";
  // Company-name matches ("apple" -> AAPL), fetched only while the sidebar search has text (lazy, see useCompanies).
  const companies = useCompanies(query, searching);

  const toggle = (c: Category) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(c)) next.add(c);
      return next;
    });

  const row = (f: Def, i: number) => (
    <button
      key={f.code}
      type="button"
      className={"gs-item" + (f.load ? "" : " dim") + (searching && i === 0 ? " top" : "")}
      title={f.title}
      data-code={f.code}
      onClick={() => runCommand(f.code)}
    >
      <span className="gs-code">{f.code}</span>
      <span className="gs-title">{f.title}</span>
    </button>
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    if (!e.ctrlKey && !e.altKey && !e.metaKey) {
      // Arrow keys walk the focusable rows (search box, group headers, function rows) in order.
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        moveFocus(root.current!, ".gs-search, .gs-task, .gs-head, .gs-item", e.key === "ArrowDown" ? 1 : -1);
      }
    }
    chromeKeyDown(e);
  };

  return (
    <aside className="gs" ref={root} data-testid="gui-sidebar" aria-label="Functions" onKeyDown={onKeyDown}>
      <input
        className="gs-search"
        data-testid="gui-search"
        type="text"
        spellCheck={false}
        autoComplete="off"
        placeholder="Search or type a command"
        aria-label="Search functions, or type a command and press Enter"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== "Enter" || e.ctrlKey || e.altKey || e.metaKey) return;
          e.preventDefault();
          const cmd = sidebarEnter(query, matches[0], isFunction);
          // Clear the box only when the command ran (a failed one keeps its text and the error shows in the top bar).
          if (cmd !== null) void (/\s/.test(cmd) ? runTyped(cmd) : Promise.resolve(runCommand(cmd))).then((ok) => ok && setQuery(""));
        }}
      />
      <div className="gs-list">
        {!searching && (
          // Not a ".gs-head": the category headers are counted by the shell test, and this group is always open.
          <section className="gs-start" data-testid="start-here" aria-label="Start here">
            <div className="gs-start-title">Start here</div>
            {START_HERE.map((t) => (
              <button key={t.label} type="button" className="gs-task" onClick={() => runCommand(t.text)}>
                <span>{t.label}</span>
                <small>{t.code}</small>
              </button>
            ))}
          </section>
        )}
        {searching && companies.length > 0 && (
          <div className="gs-companies" aria-label="Matching stocks">
            {companies.slice(0, 4).map((h) => (
              <button key={h.symbol} type="button" className="gs-item gs-company" data-symbol={h.symbol} onClick={() => runSymbol(h.symbol)}>
                <span className="gs-code">{h.symbol}</span>
                <span className="gs-title">{h.name}</span>
              </button>
            ))}
          </div>
        )}
        {searching ? (
          matches.length ? (
            matches.map((f, i) => (
              <div key={f.code} className="gs-hit">
                {row(f, i)}
                <span className="gs-cat dim">{categoryOf(f.code)}</span>
              </div>
            ))
          ) : (
            <div className="gs-empty dim">No function matches. Enter runs it as a command.</div>
          )
        ) : (
          groups.map((g) => {
            const isOpen = !collapsed.has(g.category);
            return (
              <section key={g.category} className="gs-group">
                <button type="button" className="gs-head" aria-expanded={isOpen} onClick={() => toggle(g.category)}>
                  <span className="gs-caret" aria-hidden="true">{isOpen ? "-" : "+"}</span>
                  {g.category}
                  <span className="dim"> {g.items.length}</span>
                </button>
                {isOpen && g.items.map(row)}
              </section>
            );
          })
        )}
      </div>
    </aside>
  );
}
