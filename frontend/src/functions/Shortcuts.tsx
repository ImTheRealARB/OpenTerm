import { ACTION_LABELS, KEYBINDINGS, type Action } from "../keys/keys";

export default function Shortcuts() {
  return (
    <div>
      <h2>SHORTCUTS</h2>
      <table className="t">
        <colgroup>
          <col style={{ width: 260 }} />
          <col />
        </colgroup>
        <tbody>
          {(Object.keys(KEYBINDINGS) as Action[]).map((a) => (
            <tr key={a}>
              <td className="acc">{KEYBINDINGS[a].join("  ")}</td>
              <td>{ACTION_LABELS[a].toUpperCase()}</td>
            </tr>
          ))}
          <tr>
            <td className="acc">↑ ↓ / TAB / ENTER / SHIFT+ENTER</td>
            <td>COMMAND LINE: HISTORY OR SUGGESTIONS / ACCEPT / RUN / RUN IN NEW PANEL</td>
          </tr>
        </tbody>
      </table>
      <div className="dim">
        BROWSERS RESERVE CTRL+W AND CTRL+1..9 (USE ALT+W, ALT+1..9). THE DESKTOP BUILD HAS NO SUCH LIMIT. TYPING ANY LETTER STARTS A COMMAND.
      </div>
    </div>
  );
}
