import { FUNCTIONS, showsSecurity } from "../functions/registry";
import { MAX_PANELS } from "../state/layoutState";
import { useStore } from "../state/store";
import { closePanel, currentView, focusPanel, panelOrder, split, workspace, type PanelState } from "../state/workspace";
import { chromeKeyDown, focusCommandLine } from "./chrome";
import { tabParts, type TabParts } from "./tabLabel";

/** What a tab says: a function badge ("GP") plus the ticker (when the function uses one) or its plain title; see gui/tabLabel.ts. */
function tabLabel(p: PanelState): TabParts {
  const v = currentView(p);
  return tabParts(v.fn, v.security?.symbol, showsSecurity(v), v.fn ? FUNCTIONS.get(v.fn)?.title : undefined);
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
        const label = tabLabel(p);
        return (
          <span key={id} className={"gt-tab" + (id === focus ? " on" : "")} data-panel-tab={id}>
            <button type="button" role="tab" aria-selected={id === focus} className="gt-name" onClick={() => focusPanel(id)} title={`Panel ${id}`}>
              {label.badge && (
                <span className="gt-fn" data-testid="tab-fn">
                  {label.badge}
                </span>
              )}
              <span className="gt-title">{label.title}</span>
            </button>
            <button type="button" className="gt-x" aria-label={`Close tab ${label.full}`} title="Close this tab" onClick={() => closePanel(id)}>
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
