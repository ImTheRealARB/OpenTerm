# Excel bridge

OpenTerm answers a few read-only addresses that Excel can call while OpenTerm runs on the same computer. Nothing in a workbook can
place an order or change a setting: the bridge is GET only, and it answers only requests from this computer (`127.0.0.1`). In
remote mode (`OPENTERM_REMOTE=1`) it is off.

A ready workbook is in [docs/excel/OpenTerm_examples.xlsx](excel/OpenTerm_examples.xlsx) (rebuild it with
`python scripts/make_excel_workbook.py --port 8000` if your OpenTerm uses another port).

## Addresses

| Address | Answer |
|---|---|
| `http://127.0.0.1:8000/api/xl/last?s=AAPL` | The last price as plain text, e.g. `343.46`. |
| `http://127.0.0.1:8000/api/xl/field?s=AAPL&f=pe` | One snapshot field from `FLD` (pe, fpe, pb, ps, mcap, divy, beta, eps, sector ...). Empty text when the source has no value. |
| `http://127.0.0.1:8000/api/xl/query.csv?q=<QRY>` | Any `QRY` as CSV, the same rows the QRY panel shows (URL-encode the query). |
| `http://127.0.0.1:8000/api/xl/history.csv?s=AAPL&range=1Y&interval=1d` | Bars as CSV: `date` (UTC), open, high, low, close, adj_close, volume. |

Units: ratios stay ratios (`divy` 0.012 = 1.2%, `netmargin` 0.25 = 25%); `pct` (today's change) is in percent. A failed call answers
with an HTTP error, which `WEBSERVICE()` shows as `#VALUE!`; wrap it in `IFERROR()` where a blank is better.

## Formulas (Excel for Windows 2013 and later)

```
=VALUE(WEBSERVICE("http://127.0.0.1:8000/api/xl/last?s="&A2))
=IFERROR(VALUE(WEBSERVICE("http://127.0.0.1:8000/api/xl/field?s="&A2&"&f=pe")),"")
```

`WEBSERVICE()` is not in Excel for Mac or Excel on the web: use the CSV addresses there. Excel does not refresh `WEBSERVICE()` on a
timer: press F9 (or Ctrl+Alt+F9) to recalculate.

## Power Query (Data > Get Data > From Web, or Advanced Editor)

History of one symbol:

```
let
    Source = Csv.Document(Web.Contents("http://127.0.0.1:8000/api/xl/history.csv", [Query = [s = "AAPL", range = "5Y", interval = "1d"]]),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Header, {{"date", type datetimezone}, {"open", type number}, {"high", type number},
                                                {"low", type number}, {"close", type number}, {"adj_close", type number}, {"volume", Int64.Type}})
in
    Typed
```

A screen:

```
let
    Q = "QRY last, pe, mcap, sector FOR MEMB:SPY WHERE pe<20 SORT mcap LIMIT 100",
    Source = Csv.Document(Web.Contents("http://127.0.0.1:8000/api/xl/query.csv", [Query = [q = Q]]), [Delimiter = ",", Encoding = 65001]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true])
in
    Header
```

Power Query asks how to connect the first time: choose Anonymous. Refresh with Data > Refresh All.

## QRY in short

```
QRY <fields> FOR <universe> [WHERE <field><op><value> AND ...] [SORT <field> ASC|DESC] [LIMIT n]
QRY <history fields> FOR <symbols> DATES <from>..<to> [FREQ D|W|M]
```

Universes: `SPX NDX DJI RUT MID`, `MEMB:<ETF>`, `WL:<watchlist>`, `LIST:A,B` or just `A,B`, `NIFTY50 NIFTY500`, `US` (the whole US
screener file). In `DATES` mode a symbol can be a FRED series, `FRED:DGS10`, read with the field `value`. `FLD` in the app (or
`/api/query/fields?q=<words>`) lists every field with its source, unit, update frequency and key.
