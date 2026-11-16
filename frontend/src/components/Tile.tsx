import type { ReactNode } from "react";
import { execute } from "../command/execute";
import { chromeKeyDown } from "../gui/chrome";
import { focusPanel } from "../state/workspace";
import "./tile.css";

/**
 * A section tile: a bordered block with a dark-grey header strip showing the section's title on the left and, when the
 * section has a bigger function behind it, a `CODE >` drill link on the right ("Price ... GP >").
 *
 * The link is a real <button>, so Tab reaches it and Enter / Space / click all run it. It runs the SAME text you would type
 * on the command line (`AAPL GP`), in this tile's panel, through `execute()`: one code path, so history, the sticky security
 * and every error message behave exactly as if the command was typed. With no `security` it runs the bare code (HOME's
 * tiles: `WEI`, `N TECH`).
 *
 * Plain keys typed while the link has focus must not ALSO reach the panel's key handler (Enter would open a row AND the
 * link, and the global Tab = next panel would steal the focus move), so the keydown goes through `chromeKeyDown`, the same
 * guard the GUI toolbar buttons use. Esc puts focus back on the command line.
 *
 * Looks (tile.css): terminal = square corners, 1px border, no hover. GUI = small radius and a hover colour.
 */
export interface TileProps {
  /** Header text, e.g. "Price" or "TOP HEADLINES". */
  title: string;
  /** Function code shown on the link ("GP" shows `GP >`). No code = no link. */
  code?: string;
  /** What to run when the link is used, when it is more than the bare code ("N TECH"). Defaults to `code`. */
  run?: string;
  /** The security the link opens the function for (DES passes its own ticker). Omit for market-wide tiles. */
  security?: string;
  /** The panel this tile lives in: the link focuses it, then runs there. */
  panelId: number;
  /** Small extra header content shown between the title and the link (HOME: source and age of a news block). */
  meta?: ReactNode;
  /** Extra class on the outer element (HOME: `hb`, plus `on` for the block under the cursor). */
  className?: string;
  testId?: string;
  children: ReactNode;
}

export function Tile({ title, code, run, security, panelId, meta, className, testId, children }: TileProps) {
  const open = () => {
    focusPanel(panelId);
    const cmd = run ?? code!;
    void execute(security ? `${security} ${cmd}` : cmd);
  };
  return (
    <section className={"tile" + (className ? ` ${className}` : "")} data-testid={testId}>
      <div className="tile-h">
        <span className="tile-t">{title}</span>
        {meta}
        {code && (
          <button
            type="button"
            className="tile-go"
            data-testid={testId ? `${testId}-go` : undefined}
            title={`Open ${security ? `${security} ` : ""}${run ?? code}`}
            aria-label={`${title}: open ${run ?? code}`}
            onKeyDown={chromeKeyDown}
            onClick={open}
          >
            {code} &gt;
          </button>
        )}
      </div>
      <div className="tile-b">{children}</div>
    </section>
  );
}
