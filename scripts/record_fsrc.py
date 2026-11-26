"""Record the real answers behind FSRC (the ETF screener) into backend/tests/fixtures. Keyless; run it once and commit the files.

    python scripts/record_fsrc.py

It writes two files:

  nasdaqtrader_etf_trimmed.json   the Nasdaq Trader symbol file (https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt) cut to
                                  the header, the footer, the ETFs listed in ETFS below, two stocks and the two exchange TEST ETFs
                                  (so the parser's "skip stocks and test issues" rules are exercised by real lines).
  yahoo_fundprofile_etf.json      {"status": 200, "body": {SYMBOL: <the quoteSummary answer, unchanged>}} for each ETF in ETFS, asked
                                  with the same modules `providers/etf.py` uses (FUND_MODULES). `providers/fixtures.py` routes on the symbol.

Yahoo needs the session cookie + crumb a browser gets (fc.yahoo.com, then getcrumb with Accept */*: it answers 406 to "application/json").
The calls are spaced about half a second apart. Nothing secret is involved, so nothing is redacted.
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures"
SYMBOL_FILE = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
MODULES = "fundProfile,summaryDetail"  # keep equal to providers/etf.py FUND_MODULES
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# 30 real ETFs. AIQU is a leveraged ETN the file flags as an ETF: Yahoo answers it with no fund profile at all (the "no fund data" case).
ETFS = [
    "SPY", "QQQ", "VOO", "VTI", "IVV", "IWM", "EEM", "TLT", "AGG", "BND",
    "GLD", "SLV", "XLK", "XLF", "XLE", "XLV", "LQD", "HYG", "DIA", "VNQ",
    "VEA", "SCHD", "JEPI", "SOXL", "TQQQ", "ARKK", "IBIT", "USO", "UUP", "AIQU",
]
OTHER_LINES = ["A", "AA", "ZZZTE", "ZZZTT"]  # two stocks and the two TEST ETFs: the parser must skip all four

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with opener.open(req, timeout=40) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def record_symbol_file() -> None:
    status, raw = get(SYMBOL_FILE)
    assert status == 200, status
    lines = raw.decode("utf-8").splitlines()
    header, footer = lines[0], lines[-1]
    assert footer.startswith("File Creation Time"), footer
    by_symbol = {ln.split("|")[1]: ln for ln in lines[1:-1]}
    want = [*OTHER_LINES, *ETFS]
    missing = [s for s in want if s not in by_symbol]
    assert not missing, f"not in the symbol file: {missing}"
    text = "\r\n".join([header, *(by_symbol[s] for s in want), footer]) + "\r\n"  # the real file uses CRLF
    rec = {"status": 200, "content_type": "text/plain", "text": text}
    (FIXTURES / "nasdaqtrader_etf_trimmed.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8", newline="\n")
    print("nasdaqtrader_etf_trimmed", len(want), "lines")


def record_profiles() -> None:
    get("https://fc.yahoo.com")  # answers 404 but sets the cookie
    status, crumb = get("https://query1.finance.yahoo.com/v1/test/getcrumb")
    assert status == 200 and crumb, status
    q = urllib.parse.quote(crumb.decode())
    bodies: dict[str, object] = {}
    for sym in ETFS:
        status, raw = get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules={MODULES}&crumb={q}")
        assert status == 200, f"{sym}: HTTP {status}"
        bodies[sym] = json.loads(raw)
        time.sleep(0.5)
    rec = {"status": 200, "recorded": date.today().isoformat(), "modules": MODULES, "body": bodies}
    (FIXTURES / "yahoo_fundprofile_etf.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8", newline="\n")
    print("yahoo_fundprofile_etf", len(bodies), "funds")


if __name__ == "__main__":
    record_symbol_file()
    record_profiles()
