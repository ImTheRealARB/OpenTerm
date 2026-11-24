/**
 * The line every REPLAYED panel (TAS / FOOT / DOM with `REC=<id>`) shows right under its title: it says the picture is a
 * recording, not live data, and by whom and when. Wording lives in `recArgs.recordedLabel` so the three panels cannot drift.
 */
import type { RecordedInfo } from "../net/recorderTypes";
import { recordedLabel } from "./recArgs";

export function RecordedLine({ rec, extra }: { rec: RecordedInfo; extra?: string }) {
  return (
    <div className="line warn" data-testid="rec-label">
      {recordedLabel(rec.started)} · NOT LIVE
      {rec.reason && rec.reason !== "STOPPED" && rec.reason !== "SERVER STOPPED" ? ` · ENDED: ${rec.reason}` : ""}
      {rec.truncated ? " · FILE TOO BIG: ONLY ITS NEWEST PART IS SHOWN" : ""}
      {extra ? ` · ${extra}` : ""}
    </div>
  );
}
