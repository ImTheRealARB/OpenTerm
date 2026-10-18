/** Status bar: active alert count, and the last fired alert in reverse video for 15 s (Phase 8). */
import { useEffect, useState } from "react";
import { alerts, lastFired, newsAlerts } from "../command/alerts";
import { useStore } from "../state/store";

const FLASH_MS = 15_000;

export function AlertFlash() {
  const priced = useStore(alerts, (l) => l?.filter((a) => a.status === "active").length ?? 0);
  const worded = useStore(newsAlerts, (l) => l?.filter((a) => a.status === "active").length ?? 0);
  const active = priced + worded;
  const fired = useStore(lastFired, (f) => f);
  const [, tick] = useState(0);
  const flashing = !!fired && Date.now() - fired.at < FLASH_MS;
  useEffect(() => {
    if (!fired) return;
    const left = FLASH_MS - (Date.now() - fired.at);
    if (left <= 0) return;
    const t = setTimeout(() => tick((n) => n + 1), left);
    return () => clearTimeout(t);
  }, [fired]);
  if (flashing) return <span className="alrt-flash" role="alert">{fired!.text}</span>;
  return (
    <span>
      ALRT <span className={active ? "acc" : "dim"}>{active}</span>
    </span>
  );
}
