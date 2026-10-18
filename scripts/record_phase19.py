"""Records the keyless Phase 19 fixtures, one source group per step. No key is used, nothing secret is stored.

Run from backend/:  uv run python ../scripts/record_phase19.py [step ...]      (default: every step that has a recorder)
Writes backend/tests/fixtures/<name>.json as {"status", "body"} (JSON) or {"status", "text", "content_type"} (text), like every other
recording. Big answers are trimmed; each trim is noted next to the line that makes it. A source that does not answer stops that step
(nothing is invented): the step's function is then built against a doc-shaped fixture and labelled NOT A RECORDING.
"""

import json
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
JSON_ACCEPT = {"User-Agent": UA, "Accept": "application/json"}


def save_json(name: str, body) -> None:
    (OUT / f"{name}.json").write_bytes(json.dumps({"status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: json")


def save_text(name: str, text: str, content_type: str) -> None:
    rec = {"status": 200, "text": text, "content_type": content_type}
    (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: {len(text)} chars")


def get(url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    r = httpx.get(url, params=params, headers=headers or JSON_ACCEPT, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r


def step2() -> None:
    """GP event markers: Nasdaq earnings history (last four reported quarters)."""
    save_json("nasdaq_earnings_surprise_aapl", get("https://api.nasdaq.com/api/company/AAPL/earnings-surprise").json())


def step4() -> None:
    """SECF: OpenFIGI v3 mapping (keyless, 25 requests / 6 s). One recording holds the per-identifier job result, keyed by `<idType>:<idValue>`."""
    import time

    jobs = [("ID_ISIN", "US0378331005"), ("ID_ISIN", "US5949181045"), ("ID_CUSIP", "037833100"), ("ID_SEDOL", "2046251"),
            ("ID_BB_GLOBAL", "BBG000B9XRY4"), ("ID_ISIN", "US0000000002")]  # the last one is a valid-looking ISIN nobody holds
    r = httpx.post("https://api.openfigi.com/v3/mapping", json=[{"idType": t, "idValue": v} for t, v in jobs],
                   headers={"User-Agent": UA, "Content-Type": "application/json"}, timeout=30)
    print("status", r.status_code, "ratelimit", {k: v for k, v in r.headers.items() if "limit" in k.lower() or "ratelimit" in k.lower()})
    r.raise_for_status()
    results = r.json()
    assert len(results) == len(jobs)
    table = {f"{t}:{v}": res for (t, v), res in zip(jobs, results)}
    for res in table.values():  # keep the fixture small: the first five listings per identifier
        if "data" in res:
            res["data"] = res["data"][:5]
    save_json("openfigi_mapping", table)
    time.sleep(1)


G20 = "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;KOR;MEX;RUS;SAU;ZAF;TUR;GBR;USA"
WECO_INDICATORS = {"gdp_growth": "NY.GDP.MKTP.KD.ZG", "inflation": "FP.CPI.TOTL.ZG", "unemployment": "SL.UEM.TOTL.ZS",
                   "debt_gdp": "GC.DOD.TOTL.GD.ZS", "current_account": "BN.CAB.XOKA.GD.ZS"}


def step5() -> None:
    """ECST / WECO / CENB / holidays: World Bank, DBnomics, Nager.Date, FRED policy-rate CSV, ECB and BoC policy rates."""
    wb = "https://api.worldbank.org/v2"
    save_json("worldbank_usa_gdp_growth", get(f"{wb}/country/USA/indicator/NY.GDP.MKTP.KD.ZG", {"format": "json", "per_page": 80}).json())
    save_json("worldbank_usa_gdppc", get(f"{wb}/country/USA/indicator/NY.GDP.PCAP.CD", {"format": "json", "per_page": 80}).json())
    save_json("worldbank_countries_g20", get(f"{wb}/country/{G20}", {"format": "json", "per_page": 60}).json())
    for key, code in WECO_INDICATORS.items():  # mrnev=1: each country's most recent non-empty value, with its own year
        save_json(f"worldbank_g20_{key}", get(f"{wb}/country/{G20}/indicator/{code}", {"format": "json", "mrnev": 1, "per_page": 60}).json())
    save_json("dbnomics_imf_weo_usa_ngdp_rpch", get("https://api.db.nomics.world/v22/series/IMF/WEO:latest/USA.NGDP_RPCH", {"observations": 1, "format": "json"}).json())
    for cc in ("GB", "JP", "HK"):
        r = httpx.get(f"https://date.nager.at/api/v3/PublicHolidays/2026/{cc}", headers=JSON_ACCEPT, timeout=30)
        print(cc, r.status_code, len(r.content))
        if r.status_code == 200:
            save_json(f"nager_{cc.lower()}_2026", r.json())
    # The Fed's DFEDTARU rate reuses the Phase 7 recording fred_csv_DFEDTARU.
    save_json("ecb_policy_rate_mrr", get("https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.MRR_FR.LEV", {"format": "jsondata", "lastNObservations": 5}).json())
    boe = httpx.get("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
                    params={"csv.x": "yes", "Datefrom": "01/Jan/2025", "Dateto": "31/Dec/2030", "SeriesCodes": "IUDBEDR", "CSVF": "TN", "UsingCodes": "Y"},
                    headers={"User-Agent": UA, "Accept": "text/csv,*/*"}, timeout=30)
    print("boe", boe.status_code, boe.text[:200].replace(chr(10), "|"))
    boe.raise_for_status()
    save_text("boe_bank_rate", boe.text, "text/csv")
    save_json("boc_policy_rate", get("https://www.bankofcanada.ca/valet/observations/V39079/json", {"recent": 5}).json())


FRED_PLAIN = {"User-Agent": "OpenTerm/0.1", "Accept": "text/csv,*/*"}  # fredgraph hangs on a browser User-Agent
# WCESTUS1, WCRFPUS2, WGTSTUS1, MCRFPUS2 and the other EIA weekly stocks / production ids answer 404 on fredgraph (probed 2026-10-18): NRG has prices only.
# DCOILWTICO keeps its Phase 7 recording (cosd=2021-10-01), so it is not re-recorded here.
NRG_IDS = ["DCOILBRENTEU", "DHHNGSP", "GASREGW", "GASDESW", "DGASNYH", "DGASUSGULF", "DDFUELNYH", "DHOILNYH", "DJFUELUSGULF", "DPROPANEMBTX"]
WETR_CITIES = [("New York", 40.71, -74.01), ("Chicago", 41.88, -87.63), ("Boston", 42.36, -71.06), ("Philadelphia", 39.95, -75.17),
               ("Detroit", 42.33, -83.05), ("Houston", 29.76, -95.37), ("Atlanta", 33.75, -84.39), ("Dallas", 32.78, -96.80),
               ("London", 51.51, -0.13), ("Berlin", 52.52, 13.41)]


def step6() -> None:
    """NRG / WETR: FRED CSV energy series (cosd=2025-09-01), Open-Meteo forecast + geocoding, NWS active alerts."""
    for sid in NRG_IDS:
        r = httpx.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": sid, "cosd": "2025-09-01"}, headers=FRED_PLAIN, timeout=30)
        print(sid, r.status_code, len(r.text), r.text[:60].replace(chr(10), "|"))
        if r.status_code == 200 and r.text.startswith("observation_date"):
            save_text(f"fred_csv_{sid}", r.text, "text/csv")
    lat = ",".join(str(c[1]) for c in WETR_CITIES)
    lon = ",".join(str(c[2]) for c in WETR_CITIES)
    daily = "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,wind_speed_10m_max,weather_code"
    save_json("openmeteo_forecast_basket", get("https://api.open-meteo.com/v1/forecast", {"latitude": lat, "longitude": lon, "daily": daily, "timezone": "auto", "forecast_days": 7}).json())
    save_json("openmeteo_forecast_houston", get("https://api.open-meteo.com/v1/forecast", {"latitude": 29.76, "longitude": -95.37, "daily": daily, "timezone": "auto", "forecast_days": 7}).json())
    save_json("openmeteo_geocode_houston", get("https://geocoding-api.open-meteo.com/v1/search", {"name": "Houston", "count": 5, "language": "en", "format": "json"}).json())
    save_json("openmeteo_geocode_nowhere", get("https://geocoding-api.open-meteo.com/v1/search", {"name": "Zzqqxxvv", "count": 5, "language": "en", "format": "json"}).json())
    r = httpx.get("https://api.weather.gov/alerts/active", params={"point": "29.76,-95.37"}, headers={"User-Agent": "OpenTerm-recorder/0.1", "Accept": "application/geo+json"}, timeout=30)
    print("nws", r.status_code, len(r.content))
    r.raise_for_status()
    save_json("nws_alerts_houston", r.json())
    r = httpx.get("https://api.weather.gov/alerts/active", params={"area": "TX"}, headers={"User-Agent": "OpenTerm-recorder/0.1", "Accept": "application/geo+json"}, timeout=30)
    body = r.json()
    body["features"] = body.get("features", [])[:3]  # keep three real alerts for the parser (the Houston point can be quiet)
    save_json("nws_alerts_tx", body)
    # A point query that really returns alerts: the centroid of an alert polygon in the TX answer (34.1471,-98.5971, a flood advisory near Wichita Falls).
    r = httpx.get("https://api.weather.gov/alerts/active", params={"point": "34.1471,-98.5971"}, headers={"User-Agent": "OpenTerm-recorder/0.1", "Accept": "application/geo+json"}, timeout=30)
    body = r.json()
    body["features"] = body.get("features", [])[:3]
    print("nws point", r.status_code, len(body["features"]), "(alerts expire: an empty answer means the recording needs a new point)")
    save_json("nws_alerts_point", body)


STEPS = {2: step2, 4: step4, 5: step5, 6: step6}

MAJORS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX", "BCH", "ATOM", "NEAR"]


def step7() -> None:
    """Crypto depth: Binance spot depth + USD-M futures, OKX books / funding / liquidations, DefiLlama stablecoins + yields. Big answers are trimmed (noted per line)."""
    h = {"User-Agent": "OpenTerm-recorder/0.1", "Accept": "application/json"}
    bn, fa, okx = "https://api.binance.com", "https://fapi.binance.com", "https://www.okx.com"
    save_json("binance_depth_btcusdt", get(f"{bn}/api/v3/depth", {"symbol": "BTCUSDT", "limit": 100}, h).json())
    prem = get(f"{fa}/fapi/v1/premiumIndex", None, h).json()
    keep = {f"{m}USDT" for m in MAJORS}
    save_json("binance_premium_all", [x for x in prem if x["symbol"] in keep or ("_" in x["symbol"] and x["symbol"].split("_")[0] in keep)])  # majors + the quarterlies
    save_json("binance_premium_btcusdt", get(f"{fa}/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"}, h).json())
    save_json("binance_funding_history_btcusdt", get(f"{fa}/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": 30}, h).json())
    info = get(f"{fa}/fapi/v1/fundingInfo", None, h).json()
    save_json("binance_funding_info", [x for x in info if x["symbol"] in keep or x.get("fundingIntervalHours") != 8][:60])  # majors plus the non-8h symbols
    save_json("okx_books_btcusdt", get(f"{okx}/api/v5/market/books", {"instId": "BTC-USDT", "sz": 100}, h).json())
    want_swap = {f"{m}-USDT-SWAP" for m in MAJORS}
    fr = get(f"{okx}/api/v5/public/funding-rate", {"instId": "ANY"}, h).json()
    fr["data"] = [x for x in fr["data"] if x["instId"] in want_swap]
    save_json("okx_funding_any", fr)
    mk = get(f"{okx}/api/v5/public/mark-price", {"instType": "SWAP"}, h).json()
    mk["data"] = [x for x in mk["data"] if x["instId"] in want_swap]
    save_json("okx_mark_swap", mk)
    ix = get(f"{okx}/api/v5/market/index-tickers", {"quoteCcy": "USDT"}, h).json()
    ix["data"] = [x for x in ix["data"] if x["instId"] in {f"{m}-USDT" for m in MAJORS}]
    save_json("okx_index_usdt", ix)
    save_json("okx_funding_history_btc", get(f"{okx}/api/v5/public/funding-rate-history", {"instId": "BTC-USDT-SWAP", "limit": 30}, h).json())
    save_json("okx_liq_btcusdt", get(f"{okx}/api/v5/public/liquidation-orders", {"instType": "SWAP", "uly": "BTC-USDT", "state": "filled"}, h).json())
    save_json("okx_instruments_btcusdt", get(f"{okx}/api/v5/public/instruments", {"instType": "SWAP", "uly": "BTC-USDT"}, h).json())
    st = get("https://stablecoins.llama.fi/stablecoins", {"includePrices": "true"}, h).json()
    st["peggedAssets"] = sorted(st["peggedAssets"], key=lambda a: -((a.get("circulating") or {}).get("peggedUSD") or 0))[:25]  # the 25 largest coins
    save_json("llama_stablecoins", st)
    pools = get("https://yields.llama.fi/pools", None, h).json()
    rows = sorted(pools["data"], key=lambda p: -(p.get("tvlUsd") or 0))
    pools["data"] = rows[:300] + rows[-60:]  # the 300 largest pools plus 60 tiny ones (the TVL filter has something to drop)
    save_json("llama_yields", pools)
    r = httpx.get("https://api.llama.fi/emissions", headers=h, timeout=30)
    print("emissions", r.status_code, r.text[:80])
    (OUT / "llama_emissions_probe.json").write_bytes(json.dumps({"status": r.status_code, "text": r.text, "content_type": r.headers.get("content-type", "")}, separators=(",", ":")).encode("utf-8"))


STEPS[7] = step7

POLY = "https://gamma-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLY_KEEP = ("id", "question", "conditionId", "slug", "endDate", "endDateIso", "liquidity", "liquidityNum", "outcomes", "outcomePrices", "volume", "volumeNum",
             "volume24hr", "active", "closed", "archived", "clobTokenIds", "lastTradePrice", "bestBid", "bestAsk", "updatedAt", "groupItemTitle")
KALSHI_DROP = ("rules_primary", "rules_secondary", "price_ranges", "early_close_condition", "custom_strike", "mve_selected_legs", "mve_collection_ticker")


def step8() -> None:
    """PRED: Polymarket (gamma list, a closed sample, one market, CLOB price history) and Kalshi (open markets, one market, hourly candlesticks)."""
    import time

    def trim_poly(m: dict) -> dict:  # drop images, long descriptions, order-book plumbing; keep every field PRED reads (shapes untouched)
        out = {k: m[k] for k in POLY_KEEP if k in m}
        ev = (m.get("events") or [{}])[0]
        out["events"] = [{"title": ev.get("title"), "slug": ev.get("slug")}]
        return out

    top = get(f"{POLY}/markets", {"limit": 100, "active": "true", "closed": "false", "order": "volumeNum", "ascending": "false"}).json()
    save_json("polymarket_markets", [trim_poly(m) for m in top])  # 100 markets by volume, trimmed from ~560 KB
    closed = get(f"{POLY}/markets", {"limit": 5, "closed": "true", "order": "volumeNum", "ascending": "false"}).json()
    save_json("polymarket_markets_closed", [trim_poly(m) for m in closed])  # real closed markets, for the closed-market filter test
    lead = top[0]
    one = get(f"{POLY}/markets/{lead['id']}").json()
    save_json(f"polymarket_market_{lead['id']}", trim_poly(one))
    token = json.loads(lead["clobTokenIds"])[0]  # the YES token
    hist = httpx.get("https://clob.polymarket.com/prices-history", params={"market": token, "interval": "1m", "fidelity": 240}, headers=JSON_ACCEPT, timeout=30)
    print("clob prices-history", hist.status_code, len(hist.content))
    hist.raise_for_status()
    save_json("polymarket_prices_history", hist.json())

    # Kalshi: /markets has no volume ordering and holds >12,000 open markets, nearest close first (page one is today's sports props). PRED reads two 1000-market
    # pages (multivariate combos excluded): the nearest-closing page and the page closing 30+ days out (elections, macro, long bets), merged and sorted by volume.
    near = get(f"{KALSHI}/markets", {"limit": 1000, "status": "open", "mve_filter": "exclude"}).json()["markets"]
    time.sleep(1)
    far = get(f"{KALSHI}/markets", {"limit": 1000, "status": "open", "mve_filter": "exclude", "min_close_ts": int(time.time()) + 30 * 86400}).json()["markets"]
    kal = list({m["ticker"]: m for m in near + far}.values())
    kal.sort(key=lambda m: -float(m.get("volume_fp") or 0))
    lead_k = max(far, key=lambda m: float(m.get("volume_fp") or 0))  # the busiest long-dated market: its candlesticks have a history
    picked = kal[:100] + ([lead_k] if lead_k not in kal[:100] else [])
    keep = [{k: v for k, v in m.items() if k not in KALSHI_DROP} for m in picked]
    save_json("kalshi_markets", {"markets": keep})  # top 100 by volume of the two pages, trimmed from ~4 MB
    time.sleep(1)
    one_k = get(f"{KALSHI}/markets/{lead_k['ticker']}").json()
    one_k["market"] = {k: v for k, v in one_k["market"].items() if k not in ("rules_secondary", "price_ranges")}
    save_json(f"kalshi_market_{lead_k['ticker']}", one_k)
    series = lead_k["event_ticker"].split("-")[0]
    now = int(time.time())
    cs = get(f"{KALSHI}/series/{series}/markets/{lead_k['ticker']}/candlesticks", {"start_ts": now - 7 * 86400, "end_ts": now, "period_interval": 60}).json()
    print("kalshi candlesticks", len(cs.get("candlesticks", [])))
    save_json("kalshi_candlesticks", cs)


STEPS[8] = step8


def step9() -> None:
    """Non-US zero-key data: NSE CM bhavcopy day files (zip of CSV, nsearchives.nseindia.com) and AMFI NAVAll.txt.

    NSE: the ten most recent sessions, trimmed to the same ~300 (symbol, series) rows (RELIANCE, TCS, INFY, other EQ/BE names and some other series)
    and re-zipped; the first weekday that answers 404 (an exchange holiday) is recorded as nse_bhavcopy_404. NSE's edge STALLS (read timeout, no
    answer) for a User-Agent that carries a contact string; a plain `OpenTerm` answers in 0.3 s. No cookie, no bot check was met.
    AMFI: www.amfiindia.com/spages/NAVAll.txt answers 302 to portal.amfiindia.com; the file is kept byte for byte (CRLF, blank lines that hold one
    space) but cut down to a few scheme-category blocks, each capped at 60 lines.
    """
    import base64
    import datetime as dt
    import io
    import time
    import zipfile

    nse = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
    plain = {"User-Agent": "OpenTerm", "Accept": "*/*"}
    days: list[tuple[str, str, str]] = []  # (yyyymmdd, member name, csv text)
    holiday = None
    d = dt.date.today()
    for _ in range(45):
        d -= dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        r = httpx.get(nse.format(d=d.strftime("%Y%m%d")), headers=plain, timeout=30)
        print(d, r.status_code, len(r.content))
        time.sleep(1)
        if r.status_code == 404 and holiday is None:
            holiday = {"status": 404, "text": r.text, "content_type": r.headers.get("content-type", "text/html")}
            print("holiday", d)
        elif r.status_code == 200 and len(days) < 10:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            days.append((d.strftime("%Y%m%d"), z.namelist()[0], z.read(z.namelist()[0]).decode("utf-8")))
        if len(days) >= 10 and holiday is not None:
            break
    assert len(days) == 10 and holiday is not None, "need ten sessions and one holiday in the last 45 days"
    # the kept (symbol, series) pairs come from the newest day
    rows = days[0][2].splitlines()
    head = rows[0].split(",")
    i_sym, i_ser = head.index("TckrSymb"), head.index("SctySrs")
    body = [r for r in rows[1:] if r]
    must = [r for r in body if r.split(",")[i_sym] in ("RELIANCE", "TCS", "INFY") and r.split(",")[i_ser] == "EQ"]
    other = [r for r in body if r.split(",")[i_ser] not in ("EQ", "BE")]
    seen_series: set[str] = set()
    odd = []
    for r in other:  # one row per other series, then fill up to 24
        s = r.split(",")[i_ser]
        if s not in seen_series:
            seen_series.add(s)
            odd.append(r)
    odd += [r for r in other if r not in odd][: max(0, 24 - len(odd))]
    be = [r for r in body if r.split(",")[i_ser] == "BE"][:12]
    eq = [r for r in body if r.split(",")[i_ser] == "EQ" and r not in must]
    fill = 300 - len(must) - len(odd) - len(be)
    keep_rows = must + odd + be + eq[:: max(1, len(eq) // fill)][:fill]
    keep = {(r.split(",")[i_sym], r.split(",")[i_ser]) for r in keep_rows}
    print("kept", len(keep), "series", sorted({k[1] for k in keep}))
    for ymd, member, text in days:
        lines = text.splitlines()
        out = [lines[0]] + [r for r in lines[1:] if r and (r.split(",")[i_sym], r.split(",")[i_ser]) in keep]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(member, "\n".join(out) + "\n")
        rec = {"status": 200, "b64": base64.b64encode(buf.getvalue()).decode("ascii"), "content_type": "application/zip"}
        (OUT / f"nse_bhavcopy_{ymd}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
        print(f"nse_bhavcopy_{ymd}: {len(out) - 1} rows")
    (OUT / "nse_bhavcopy_404.json").write_bytes(json.dumps(holiday, separators=(",", ":")).encode("utf-8"))

    first = httpx.get("https://www.amfiindia.com/spages/NAVAll.txt", headers=plain, timeout=60)
    print("amfi first hop", first.status_code, first.headers.get("location"))
    r = httpx.get("https://portal.amfiindia.com/spages/NAVAll.txt", headers=plain, timeout=90)
    r.raise_for_status()
    text = r.content.decode("utf-8")
    lines = text.split("\r\n")
    cats = [i for i, ln in enumerate(lines) if ";" not in ln and ln.startswith(("Open Ended", "Close Ended", "Interval"))]
    cats.append(len(lines))
    blocks = {lines[a]: (a, b) for a, b in zip(cats, cats[1:])}
    names = list(blocks)
    wanted = names[:2]
    wanted += [k for k in names if k.startswith("Close Ended")][:1] + [k for k in names if k.startswith("Interval")][:1]
    wanted += [k for k in names[2:] if 20 <= blocks[k][1] - blocks[k][0] <= 60 and k not in wanted][:4]
    wanted = list(dict.fromkeys(wanted))
    keep_lines = [lines[0], " "]
    for k in sorted(wanted, key=lambda k: blocks[k][0]):
        a, b = blocks[k]
        chunk = lines[a:b][:60]
        keep_lines += chunk
        if chunk[-1].strip():
            keep_lines.append(" ")
    save_text("amfi_navall", "\r\n".join(keep_lines) + "\r\n", "text/plain")
    print("amfi blocks", len(wanted), "lines", len(keep_lines), "of", len(lines))


STEPS[9] = step9

if __name__ == "__main__":
    wanted =[int(a) for a in sys.argv[1:]] or sorted(STEPS)
    for n in wanted:
        print(f"== step {n}")
        STEPS[n]()
