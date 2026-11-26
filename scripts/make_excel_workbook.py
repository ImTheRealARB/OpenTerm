"""Writes docs/excel/OpenTerm_examples.xlsx: a small workbook whose formulas read a running OpenTerm through the Excel bridge
(`/api/xl/...`, loopback only). Standard library only: an .xlsx file is a zip of XML parts, written here by hand.

Run from the repo root:  python scripts/make_excel_workbook.py [--port 8000]

Sheets:
  Quotes   symbols in column A; last price, P/E, market cap and today's change through WEBSERVICE() (Excel for Windows 2013+)
  Query    a QRY in A2 and the CSV link built with ENCODEURL(); paste the link into Data > From Web (or Power Query)
  History  the CSV link for one symbol's bars, for Data > From Web
  Read me  what each formula does and what it needs
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "excel" / "OpenTerm_examples.xlsx"


def col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def cell(ref: str, v: object) -> str:
    """A string becomes an inline string; text starting with '=' becomes a formula (no cached value: Excel computes it on open)."""
    if isinstance(v, str) and v.startswith("="):
        return f'<c r="{ref}"><f>{escape(v[1:])}</f></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def sheet(rows: list[list[object]], widths: list[int]) -> str:
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    body = "".join(f'<row r="{r + 1}">' + "".join(cell(f"{col(c)}{r + 1}", v) for c, v in enumerate(row) if v is not None) + "</row>"
                   for r, row in enumerate(rows))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<cols>{cols}</cols><sheetData>{body}</sheetData></worksheet>")


def build(port: int) -> dict[str, list[list[object]]]:
    base = f"http://127.0.0.1:{port}/api/xl"
    q = [["SYMBOL", "LAST", "P/E", "MARKET CAP", "CHANGE %"]]
    for i, s in enumerate(["AAPL", "MSFT", "NVDA", "RELIANCE.NS", "SPY"], start=2):
        q.append([s, f'=VALUE(WEBSERVICE("{base}/last?s="&A{i}))', f'=IFERROR(VALUE(WEBSERVICE("{base}/field?s="&A{i}&"&f=pe")),"")',
                  f'=IFERROR(VALUE(WEBSERVICE("{base}/field?s="&A{i}&"&f=mcap")),"")', f'=IFERROR(VALUE(WEBSERVICE("{base}/field?s="&A{i}&"&f=pct"))/100,"")'])
    query = [["QRY (EDIT ME)"], ["QRY last, pe, mcap FOR MEMB:SPY WHERE pe<20 SORT mcap LIMIT 50"], [],
             ["CSV LINK (COPY INTO DATA > FROM WEB)"], [f'="{base}/query.csv?q="&ENCODEURL(A2)']]
    hist = [["SYMBOL", "RANGE", "INTERVAL"], ["AAPL", "1Y", "1d"], [], ["CSV LINK (COPY INTO DATA > FROM WEB)"],
            [f'="{base}/history.csv?s="&A2&"&range="&B2&"&interval="&C2']]
    readme = [[line] for line in (
        "OPENTERM EXCEL BRIDGE",
        "Start OpenTerm first (the desktop app or `openterm`). These formulas read it on this computer only (127.0.0.1).",
        "WEBSERVICE() exists in Excel for Windows 2013 and later; Excel for Mac and the web version do not have it: use the CSV links.",
        "/api/xl/last?s=SYM        last price as plain text (wrap in VALUE()).",
        "/api/xl/field?s=SYM&f=F    one snapshot field from FLD (pe, pb, mcap, divy, beta, ...). Empty when the source has no value.",
        "/api/xl/query.csv?q=QRY   any QRY as CSV (the same rows the QRY panel shows).",
        "/api/xl/history.csv?s=SYM&range=1Y&interval=1d   bars as CSV: date (UTC), open, high, low, close, adj_close, volume.",
        "Ratios stay ratios (divy 0.012 = 1.2%); pct is in percent. Recalculate with F9 (WEBSERVICE does not refresh by itself).",
        "Read only: nothing in a workbook can place an order or change OpenTerm.",
        "Guide: docs/EXCEL.md in the OpenTerm repository.",
    )]
    return {"Quotes": q, "Query": query, "History": hist, "Read me": readme}


def write(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    names = list(sheets)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(names)))
          + "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>")
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
          + '</sheets><calcPr fullCalcOnLoad="1"/></workbook>')
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                         f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(names)))
               + "</Relationships>")
    widths = {"Quotes": [14, 12, 10, 18, 12], "Query": [90], "History": [12, 10, 10], "Read me": [130]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("[Content_Types].xml", ct), ("_rels/.rels", rels), ("xl/workbook.xml", wb), ("xl/_rels/workbook.xml.rels", wb_rels)):
            z.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), data)  # fixed timestamps: the same input gives the same bytes
        for i, n in enumerate(names):
            z.writestr(zipfile.ZipInfo(f"xl/worksheets/sheet{i + 1}.xml", (2026, 1, 1, 0, 0, 0)), sheet(sheets[n], widths[n]))


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
    write(OUT, build(port))
    print("wrote", OUT)
