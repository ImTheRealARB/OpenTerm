"""DBSRCH: find DBnomics series by words. Pure parsers (no network, no pandas); the service function behind `/api/world/dbsearch` is `macro.dbsearch`.

DBnomics (https://db.nomics.world) is a keyless mirror of statistics from the IMF, OECD, Eurostat, BIS, ECB, World Bank, national
statistics offices and more. OpenTerm can already plot any series with `ECST DBN:<provider>/<dataset>/<series>`, but nobody knows the
ids by heart. The API has two search levels, so DBSRCH works in two steps:

  1. `GET /v22/search?q=<words>`                       lists DATASETS (a dataset is one table of a provider, e.g. ECB "CSEC").
  2. `GET /v22/series/<provider>/<dataset>?q=<words>`  lists the SERIES inside one dataset that match the words.

Step 1 answers `results.docs[]` with `provider_code, provider_name, code, name, nb_matching_series, nb_series, updated_at, indexed_at`
(`updated_at` is missing for some datasets; `description` is long HTML and is never used). Step 2 answers `series.docs[]` with
`provider_code, dataset_code, series_code, series_name, indexed_at, dimensions`. We ask for `observations=0&metadata=0`, so the answer is
about 1 KB per series: that means the LAST PERIOD of a series is NOT in the list (it is only in the observations), and the chart shows it.
Frequency is read from the series' own `FREQ` dimension (SDMX code) when it has one and left blank otherwise: it is never guessed.

Every row carries the ORIGINAL provider's name, because DBnomics only mirrors the data: cite the provider, not DBnomics.
"""

from __future__ import annotations

import re
from typing import Any

from ..providers.base import ProviderError
from . import stats

MAX_QUERY = 120
# `<provider>/<dataset>`; dataset codes may hold `.`, `:` and `@` (OECD codes look like DSD_TAXBEN_NRR@DF_NRR).
DATASET_REF = re.compile(r"^([A-Za-z0-9_\-]+)/([A-Za-z0-9_.\-:@]+)$")
# SDMX frequency codes (the standard most providers follow), spelled out for the FREQ column.
FREQ_NAMES = {
    "A": "ANNUAL", "S": "SEMIANNUAL", "H": "SEMIANNUAL", "Q": "QUARTERLY", "M": "MONTHLY", "W": "WEEKLY", "D": "DAILY", "B": "DAILY (BUSINESS)",
    "ANNUAL": "ANNUAL", "QUARTERLY": "QUARTERLY", "MONTHLY": "MONTHLY", "WEEKLY": "WEEKLY", "DAILY": "DAILY",
}
NOTE = (
    "DBNOMICS COPIES EACH PROVIDER'S DATA: CITE THE ORIGINAL PROVIDER SHOWN IN THE ROW, NOT DBNOMICS. "
    "THE LAST PERIOD IS NOT IN THIS LIST: IT SHOWS WHEN YOU OPEN THE SERIES."
)


def norm_query(text: str | None, *, required: bool) -> str:
    """Search words with runs of spaces collapsed. Datasets need words (2+ characters); a series list may go without."""
    q = re.sub(r"\s+", " ", text or "").strip()
    if not q and not required:
        return ""
    if len(q) < 2:
        raise ValueError("GIVE SEARCH WORDS, E.G. DBSRCH FRANCE INFLATION OR DBSRCH OECD UNEMPLOYMENT")
    if len(q) > MAX_QUERY:
        raise ValueError(f"SEARCH IS LIMITED TO {MAX_QUERY} CHARACTERS")
    return q


def parse_dataset_ref(text: str | None) -> tuple[str, str] | None:
    """`ECB/CSEC` -> ("ECB", "CSEC"); None when it is not of that shape."""
    m = DATASET_REF.match((text or "").strip())
    return (m.group(1), m.group(2)) if m else None


def _day(stamp: Any) -> str | None:
    """`2026-06-12T00:00:00Z` -> `2026-06-12`; anything that is not text becomes None (unknown stays unknown)."""
    return stamp[:10] if isinstance(stamp, str) and len(stamp) >= 10 else None


def frequency(doc: dict[str, Any]) -> str:
    """Frequency of one series doc: its own `@frequency` (only present with observations) or the `FREQ` dimension; "" when neither says."""
    raw = doc.get("@frequency")
    if not isinstance(raw, str) or not raw:
        dims = doc.get("dimensions") if isinstance(doc.get("dimensions"), dict) else {}
        raw = next((v for k, v in dims.items() if isinstance(k, str) and k.lower() in ("freq", "frequency") and isinstance(v, str)), "")
    code = raw.strip().upper()
    return FREQ_NAMES.get(code, code)  # an unknown code is shown as the provider wrote it, never replaced


def _docs(body: Any, section: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The `docs` list and its paging block of a DBnomics answer; a different shape means the API changed or is serving an error page."""
    block = body.get(section) if isinstance(body, dict) else None
    docs = block.get("docs") if isinstance(block, dict) else None
    if not isinstance(docs, list):
        raise ProviderError("unavailable", f"DBNOMICS ANSWERED WITHOUT {section}.docs (API CHANGED?)")
    return [d for d in docs if isinstance(d, dict)], block


def parse_datasets(body: Any) -> dict[str, Any]:
    """`/v22/search` answer -> one row per dataset, in the API's own relevance order. Zero matches is a valid answer (empty items)."""
    docs, block = _docs(body, "results")
    items = []
    for d in docs:
        provider, code = d.get("provider_code"), d.get("code")
        if not isinstance(provider, str) or not isinstance(code, str):
            continue  # a row we cannot address is dropped, never patched up
        items.append({
            "provider": provider, "provider_name": d.get("provider_name") or provider, "dataset": code, "name": d.get("name") or code,
            "matching": d.get("nb_matching_series"), "series": d.get("nb_series"),
            "updated": _day(d.get("updated_at")), "indexed": _day(d.get("indexed_at")),
        })
    return {"mode": "DATASETS", "total": block.get("num_found", len(items)), "offset": block.get("offset", 0), "items": items, "note": NOTE}


def parse_series(body: Any, provider: str, dataset: str) -> dict[str, Any]:
    """`/v22/series/<provider>/<dataset>` answer -> one row per series. `ref` is the `DBN:` id ECST opens, or None when ECST cannot take that id."""
    docs, block = _docs(body, "series")
    items = []
    dataset_name = None
    for d in docs:
        code = d.get("series_code")
        if not isinstance(code, str):
            continue
        prov, ds = d.get("provider_code") or provider, d.get("dataset_code") or dataset
        dataset_name = dataset_name or d.get("dataset_name")
        ref = f"DBN:{prov}/{ds}/{code}"
        items.append({
            "provider": prov, "dataset": ds, "series": code, "name": d.get("series_name") or code, "freq": frequency(d),
            "indexed": _day(d.get("indexed_at")), "ref": ref if stats.parse_dbn_ref(ref) else None,
        })
    return {"mode": "SERIES", "provider": provider, "dataset": dataset, "dataset_name": dataset_name or dataset, "total": block.get("num_found", len(items)),
            "offset": block.get("offset", 0), "items": items, "note": NOTE}
