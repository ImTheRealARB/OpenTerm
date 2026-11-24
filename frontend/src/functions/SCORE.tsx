/** SCORE (Phase 29): Altman Z / Z'', Piotroski F, Beneish M, Ohlson O and Merton distance to default, each with its inputs. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "score",
  api: "fund",
  usage: "USAGE: <SYM> SCORE (US SEC FILERS; FORMULA SCORES, NOT A RATING)",
  keys: "FORMULA SCORE, NOT A RATING",
  params: (p) => (p.security ? { symbol: p.security.symbol } : null),
});
