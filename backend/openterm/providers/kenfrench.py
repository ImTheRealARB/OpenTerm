"""Ken French data library (Dartmouth, keyless): daily Fama-French 5 factors and the momentum factor, for `FACT`.

Both files are zips holding one CSV with header text, a block of daily rows `YYYYMMDD, v, v, ...` (percent) and trailing copyright text.
Parsed in pure Python (zipfile), no pandas: the server never imports the heavy math libraries. The library lags about two months.
"""

from __future__ import annotations

import asyncio
import zipfile
from io import BytesIO
from typing import ClassVar

from .base import Provider, ProviderError

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF5_FILE = "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOM_FILE = "F-F_Momentum_Factor_daily_CSV.zip"
FF5_COLS = ("MKT-RF", "SMB", "HML", "RMW", "CMA", "RF")
MOM_COLS = ("MOM",)
FACTORS = "factors"
MISSING = -99.0  # the library prints -99.99 / -999 for a missing value


def parse_zip(blob: bytes, cols: tuple[str, ...]) -> dict[int, list[float]]:
    """{yyyymmdd: [value per column in `cols`]} (percent) from a Ken French daily zip. Days with a missing value are dropped."""
    try:
        z = zipfile.ZipFile(BytesIO(blob))
        text = z.read(z.namelist()[0]).decode("latin-1")
    except (zipfile.BadZipFile, IndexError, KeyError) as e:
        raise ProviderError("unavailable", f"Ken French file is not a zip ({type(e).__name__})") from e
    out: dict[int, list[float]] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(cols) + 1 or len(parts[0]) != 8 or not parts[0].isdigit():
            continue
        try:
            vals = [float(p) for p in parts[1:]]
        except ValueError:
            continue
        if any(v <= MISSING for v in vals):
            continue
        out[int(parts[0])] = vals
    if not out:
        raise ProviderError("unavailable", "Ken French file holds no daily rows")
    return out


def merge(ff5: dict[int, list[float]], mom: dict[int, list[float]]) -> dict:
    """Columnar {dates: [yyyymmdd], cols: {name: [percent]}} on the days both files have, ascending."""
    dates = sorted(set(ff5) & set(mom))
    if not dates:
        raise ProviderError("unavailable", "the Ken French factor files share no day")
    cols = {name: [ff5[d][i] for d in dates] for i, name in enumerate(FF5_COLS)}
    cols["MOM"] = [mom[d][0] for d in dates]
    return {"dates": dates, "cols": cols}


class KenFrenchProvider(Provider):
    name = "kenfrench"
    label = "Ken French data library (Fama-French factors, keyless)"
    capabilities = frozenset({FACTORS})
    markets = "US daily Fama-French 5 factors + momentum (MKT-RF, SMB, HML, RMW, CMA, MOM, RF); the library lags about two months"
    terms = "Public download, no key. Data: Kenneth R. French Data Library (Tuck School of Business, Dartmouth); cite it."
    rate = (1.0, 4)
    max_wait = 4.0
    timeout = 25.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/1.0 (personal research)", "Accept": "application/zip,*/*"}

    async def factors(self) -> dict:
        ff5, mom = await asyncio.gather(self.get_bytes(BASE + FF5_FILE), self.get_bytes(BASE + MOM_FILE))
        merged = merge(parse_zip(ff5, FF5_COLS), parse_zip(mom, MOM_COLS))
        return {**merged, "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes(BASE + MOM_FILE)
