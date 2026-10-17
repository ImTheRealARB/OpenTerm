import { ACTION_LABELS, effectiveBindings, type Action } from "../keys/keys";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";

export default function Shortcuts() {
  // Effective bindings (defaults + SETTINGS overrides); re-rendered when settings change.
  const keys = useStore(settingsStore, (st) => st.keys);
  const vim = useStore(settingsStore, (st) => st.vim);
  const bindings = effectiveBindings();
  void keys;
  return (
    <div>
      <h2>SHORTCUTS</h2>
      <table className="t">
        <colgroup>
          <col style={{ width: 260 }} />
          <col />
        </colgroup>
        <tbody>
          {(Object.keys(bindings) as Action[]).map((a) => (
            <tr key={a}>
              <td className="acc">{bindings[a].join("  ") || "(UNBOUND)"}</td>
              <td>{ACTION_LABELS[a].toUpperCase()}</td>
            </tr>
          ))}
          <tr>
            <td className="acc">↑ ↓ / TAB / ENTER / SHIFT+ENTER</td>
            <td>COMMAND LINE: HISTORY OR SUGGESTIONS / ACCEPT / RUN / RUN IN NEW PANEL</td>
          </tr>
          <tr>
            <td className="acc">J K ↑ ↓ PGUP PGDN G SHIFT+G</td>
            <td>TABLES: MOVE / PAGE / TOP / BOTTOM</td>
          </tr>
          {vim && (
            <tr>
              <td className="acc">ESC h l w b e 0 $ x dd cw i a A I k j / CTRL+D CTRL+U</td>
              <td>VIM MODE: COMMAND LINE NORMAL MODE EDITING AND HISTORY / TABLES: HALF PAGE DOWN UP</td>
            </tr>
          )}
          <tr>
            <td className="acc">ENTER A D S E F5</td>
            <td>TABLES: DRILL DOWN (DES) / ADD / DELETE / SORT / EXPORT CSV / REFRESH</td>
          </tr>
          <tr>
            <td className="acc">1..8 C I L X ← → + -</td>
            <td>CHARTS: 1D 5D 1M 6M YTD 1Y 5Y MAX / TYPE / INDICATORS / LOG / CROSSHAIR / PAN / ZOOM</td>
          </tr>
        </tbody>
      </table>
      <div className="dim">
        CHANGE SHORTCUTS IN SETTINGS. BROWSERS RESERVE CTRL+W AND CTRL+1..9 (USE ALT+W, ALT+1..9). THE DESKTOP BUILD HAS NO SUCH LIMIT.
        ALT+X EXPORTS ANY TABLE PANEL (CTRL+E AND ALT+E ARE TAKEN BY BROWSERS).
        TYPING STARTS A COMMAND, EXCEPT IN GRIDS AND CHARTS WHERE LETTERS ARE PANEL KEYS: PRESS / FIRST.
      </div>
    </div>
  );
}
