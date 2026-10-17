import { DISCLAIMER } from "../config";
import { link } from "../net/socket";
import { useStore } from "../state/store";
import { workspace } from "../state/workspace";

export function StatusBar() {
  const l = useStore(link, (s) => s);
  const focus = useStore(workspace, (s) => s.focus);
  const count = useStore(workspace, (s) => Object.keys(s.panels).length);
  const max = useStore(workspace, (s) => s.maximized);
  const cls = l.status === "OK" ? "up" : l.status === "DOWN" ? "err" : "warn";
  return (
    <footer className="status">
      <span>
        BACKEND <span className={cls}>{l.status}</span>
        {l.status === "OK" && <> {l.rttMs.toFixed(0)}MS</>}
      </span>
      <span>PROVIDERS: NONE YET</span>
      <span>
        PANEL {focus}/{count}
        {max ? " MAX" : ""}
      </span>
      <span>MODE CMD</span>
      <span className="sp" />
      <span>{DISCLAIMER}</span>
    </footer>
  );
}
