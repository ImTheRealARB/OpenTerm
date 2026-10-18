/** Phase 14: the RATES tables behind an argument (EUR GBP CAD JPY, SPRD, AUCT, NS <ccy>), rendered by the shared research panel. */
import { RATES_USAGE, ratesView, type RatesViewName } from "./ratesArgs";
import { makeResearchPanel } from "./ResearchPanel";
import type { FunctionProps } from "./registry";

const forView = (view: RatesViewName) => (p: FunctionProps) => {
  const v = ratesView(p.args);
  return v && v.view === view ? v.params : null;
};

const Curve = makeResearchPanel({ fn: "curve", api: "rates", usage: RATES_USAGE, keys: "CURVE AND FIT ARE SHOWN WITH THEIR SOURCE", params: forView("curve") });
const Spreads = makeResearchPanel({ fn: "spreads", api: "rates", usage: RATES_USAGE, params: forView("spreads") });
const Auctions = makeResearchPanel({ fn: "auctions", api: "rates", usage: RATES_USAGE, params: forView("auctions") });

export default function RatesView(props: FunctionProps) {
  const v = ratesView(props.args);
  if (v?.view === "spreads") return <Spreads {...props} />;
  if (v?.view === "auctions") return <Auctions {...props} />;
  return <Curve {...props} />; // a bad argument lands here and shows the usage line
}
