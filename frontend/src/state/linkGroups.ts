/**
 * Link groups (Phase 22): panels that share a colour group A-D follow each other's security. Pure functions over the
 * workspace's panel map, so the rule is unit-tested without a store or a browser.
 */
import type { PanelState, View } from "./workspace";

export const LINK_GROUPS = ["A", "B", "C", "D"] as const;
export type LinkGroup = (typeof LINK_GROUPS)[number];

export const isLinkGroup = (x: unknown): x is LinkGroup => typeof x === "string" && (LINK_GROUPS as readonly string[]).includes(x);

/** Next group in the GUI chip's click cycle: none, A, B, C, D, none. */
export function nextGroup(g: LinkGroup | undefined): LinkGroup | undefined {
  const i = g ? LINK_GROUPS.indexOf(g) : -1;
  return i + 1 < LINK_GROUPS.length ? LINK_GROUPS[i + 1] : undefined;
}

/**
 * After panel `fromId` loaded `security`, every OTHER panel of the same group whose current view uses a security switches
 * to it, in place (no extra history entry). Panels without a group, of another group, or showing something that takes no
 * security (a watchlist, a board) are left alone. Returns the same map when nothing changes.
 */
export function propagate(
  panels: Record<number, PanelState>,
  fromId: number,
  security: View["security"],
  usesSecurity: (v: View) => boolean,
): Record<number, PanelState> {
  const group = panels[fromId]?.link;
  if (!group || !security) return panels;
  let out = panels;
  for (const p of Object.values(panels)) {
    if (p.id === fromId || p.link !== group) continue;
    const v = p.views[p.pos];
    if (!v || !usesSecurity(v) || v.security?.symbol === security.symbol) continue;
    const views = p.views.slice();
    views[p.pos] = { ...v, security };
    if (out === panels) out = { ...panels };
    out[p.id] = { ...p, views };
  }
  return out;
}
