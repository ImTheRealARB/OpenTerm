/** QRY (Phase 31): the query language over fields, universes and dates. Server: /api/query (query/engine.py), the same code the SDK
 * (`ot.query`) and the Excel bridge (`/api/xl/query.csv`) use. Enter on a snapshot row opens DES for that symbol. */
import { researchApi } from "../net/researchApi";
import { makeResearchPanel } from "./ResearchPanel";
import { macroRowKey } from "./macroRowKey";
import { QRY_USAGE, qryText } from "./qryArgs";

export default makeResearchPanel({
  fn: "qry",
  usage: QRY_USAGE,
  keys: "FLD LISTS FIELDS",
  params: (p) => {
    const q = qryText(p.args);
    return q ? { q } : null;
  },
  loader: (params) => researchApi.query(String(params.q)),
  onKey: (e, p, _d, say, row) => macroRowKey(e, p.panelId, row, say),
});
