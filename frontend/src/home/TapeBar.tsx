/** The tape in the global top bar (setting `tape` / TAPE ON). Its own chunk: App loads it only when the setting is on. */
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { TickerTape } from "./TickerTape";
import { useQuoteMap } from "./useQuoteMap";

export function TapeBar() {
  const symbols = useStore(settingsStore, (s) => s.tapeSymbols);
  const quotes = useQuoteMap(symbols);
  return <TickerTape symbols={symbols} quotes={quotes} />;
}
