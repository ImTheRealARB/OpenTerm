import { FUNCTIONS } from "../functions/registry";
import { MAX_PANELS } from "../state/layoutState";
import { useStore } from "../state/store";
import { closePanel, currentView, focusPanel, panelOrder, split, workspace, type PanelState } from "../state/workspace";
import { chromeKeyDown, focusCommandLine } from "./chrome";

/** What a tab says: "AAPL GP" (ticker only when the function uses one, like the panel title), the function alone, or "New tab". */
function tabLabel(p: PanelState): string {
  const v = currentView(p);
  const uses = (v.fn && FUNCTIONS.get(v.fn)?.needsSecurity) || (v.fn === "N" && v.args.length === 0);
  const parts = [uses ? v.security?.symbol : undefined, v.fn].filter(Boolean);
  return parts.length ? parts.join(" ") : "New tab";
}

/**
 * Browser-style tab strip for GUI mode. Each open panel is a tab; clicking one shows it full size. "+" opens a new empty tab
 * (the panel cap is 9, so the button turns off there), and the cross closes a tab. The Tabs/Tiles button in the menu bar switches to the side-by-side layout.
 * Tabs are the same panels the tiled layout has: nothing is lost when you switch between the two.
 */
export function TabStrip() {
  const panels = useStore(workspace, (s) => s.panels);
  const order = useStore(workspace, (s) => panelOrder(s).join(","))
    .split(",")
    .map(Number);
  const focus = useStore(workspace, (s) => s.focus);

  return (
    <div className="gt" role="tablist" aria-label="Open panels" data-testid="tab-strip" onKeyDown={chromeKeyDown}>
      {order.map((id) => {
        const p = panels[id];
        if (!p) return null;
        return (
          <span key={id} className={"gt-tab" + (id === focus ? " on" : "")} data-panel-tab={id}>
            <button type="button" role="tab" aria-selected={id === focus} className="gt-name" onClick={() => focusPanel(id)} title={`Panel ${id}`}>
              {tabLabel(p)}
            </button>
            <button type="button" className="gt-x" aria-label={`Close tab ${tabLabel(p)}`} title="Close this tab" onClick={() => closePanel(id)}>
              ×
            </button>
          </span>
        );
      })}
      <button
        type="button"
        className="gt-new"
        data-testid="tab-new"
        title={order.length >= MAX_PANELS ? `At most ${MAX_PANELS} tabs` : "New tab"}
        disabled={order.length >= MAX_PANELS}
        onClick={() => {
          split("v"); // adds a panel (hidden layout split) and focuses it; tabs show only the focused one
          focusCommandLine();
        }}
      >
        +
      </button>
    </div>
  );
}
