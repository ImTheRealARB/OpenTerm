import { useEffect, useState, type ComponentType } from "react";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";

type Builder = ComponentType<{ onRun: (rule: string, symbol: string) => void }>;
let cached: Builder | undefined;

/** GUI mode only: loads the rule builder (its own chunk) after the empty BT panel shows. Terminal mode renders nothing. */
export function BtRuleLazy({ onRun }: { onRun: (rule: string, symbol: string) => void }) {
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const [Comp, setComp] = useState<Builder | undefined>(cached);
  useEffect(() => {
    if (!gui || Comp) return;
    let alive = true;
    import("./BtRuleBuilder")
      .then((m) => {
        cached = m.default;
        if (alive) setComp(() => m.default);
      })
      // Ignored on purpose: the GUI rule builder is an optional helper; the BT text command works without it and a later
      // visit to this panel tries the download again.
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [gui, Comp]);
  return gui && Comp ? <Comp onRun={onRun} /> : null;
}
