import { osaStructure, rememberOsa } from "../bt/optionsStructure";
import { navigate } from "../state/workspace";
import { kvParams } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "osa",
  api: "deriv",
  usage: "USAGE: <SYM> OSA LEGS=+1C270@5.2,-1C290 | STRAT=BULLCALL,270,290 EXP=2026-12-18|T=0.5 [IV=25 R= MULT=100 COMM=pct]",
  keys: "C CHART · SHIFT+H J K L HEAT CURSOR · B BACKTEST (BT MKT=options)",
  params: (p) => {
    if (!p.security) return null;
    const { params, bad } = kvParams(p.args);
    return bad.length ? null : { symbol: p.security.symbol, ...params };
  },
  // Phase 14: remember the structure shown, so `BT <SYM> MKT=options` (or B here) can run it. Nothing is defaulted.
  onData: (d, p) => {
    if (p.security) rememberOsa(p.security.symbol, osaStructure(d, p.args));
  },
  onKey: (e, p) => {
    if (e.shiftKey || (e.key !== "b" && e.key !== "B") || !p.security) return false;
    navigate(p.panelId, { fn: "BT", security: p.security, args: [p.security.symbol, "MKT=options"] });
    return true;
  },
});
