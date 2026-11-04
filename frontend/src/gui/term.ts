/**
 * Props for a label that has a glossary entry: `<span {...termProps("EPS", gui)}>EPS (TTM)</span>`.
 * `data-term` is always rendered (harmless in Terminal mode: no tooltip, no style). In GUI mode the label also gets
 * `tabIndex=0` so a keyboard user can focus it and read the tooltip.
 */
export function termProps(term: string, gui: boolean): { "data-term": string; tabIndex?: number } {
  return gui ? { "data-term": term, tabIndex: 0 } : { "data-term": term };
}
