"""A minimal .xlsx reader (standard library only) for the Phase 30 workbooks: Atlanta Fed GDPNow and the Philadelphia Fed SPF.

Why not openpyxl: two read-only uses do not justify a new dependency, and an .xlsx file is just a zip of XML files:
    xl/workbook.xml            sheet names -> relationship ids
    xl/_rels/workbook.xml.rels relationship ids -> xl/worksheets/sheetN.xml
    xl/sharedStrings.xml       the text table; a cell with t="s" holds an index into it
    xl/worksheets/sheetN.xml   <row><c r="B3" t="s|n|str|b|inlineStr"><v>..</v></c></row>
Formulas are not evaluated: Excel stores the last computed value in <v>, which is what we read. Styles are ignored, so a date
cell comes back as its serial number (`excel_date` converts it). Pure: bytes in, lists out, no network.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, timedelta
from xml.etree.ElementTree import iterparse

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_COL = re.compile(r"^([A-Z]+)")


class XlsxError(ValueError):
    """The bytes are not a workbook we can read (not a zip, no such sheet, broken XML)."""


def _col_index(ref: str) -> int:
    """'A1' -> 0, 'AB7' -> 27 (the letters are a base-26 number with no zero)."""
    m = _COL.match(ref)
    if not m:
        raise XlsxError(f"BAD CELL REFERENCE {ref[:10]}")
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _zip(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise XlsxError("NOT AN XLSX FILE (NOT A ZIP)") from e


def sheet_names(data: bytes) -> list[str]:
    z = _zip(data)
    names = []
    for _, el in iterparse(io.BytesIO(z.read("xl/workbook.xml"))):
        if el.tag == f"{NS}sheet":
            names.append(el.get("name") or "")
    return names


def _sheet_path(z: zipfile.ZipFile, name: str) -> str:
    rid = None
    for _, el in iterparse(io.BytesIO(z.read("xl/workbook.xml"))):
        if el.tag == f"{NS}sheet" and el.get("name") == name:
            rid = el.get(f"{REL_NS}id")
    if rid is None:
        raise XlsxError(f"NO SHEET NAMED {name}")
    for _, el in iterparse(io.BytesIO(z.read("xl/_rels/workbook.xml.rels"))):
        if el.tag.endswith("Relationship") and el.get("Id") == rid:
            target = el.get("Target") or ""
            return target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    raise XlsxError(f"SHEET {name} HAS NO FILE")


def _shared(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out: list[str] = []
    for _, el in iterparse(io.BytesIO(z.read("xl/sharedStrings.xml"))):
        if el.tag == f"{NS}si":
            # A rich-text string is split into runs (<r><t>..</t></r>); join every <t> under the <si>.
            out.append("".join(t.text or "" for t in el.iter(f"{NS}t")))
            el.clear()
    return out


def read_sheet(data: bytes, name: str, max_rows: int | None = None) -> list[list[object]]:
    """Every row of one sheet as a list (missing cells are None). Numbers are floats, text is str, booleans are bool."""
    z = _zip(data)
    path = _sheet_path(z, name)
    strings = _shared(z)
    rows: list[list[object]] = []
    try:
        for _, el in iterparse(io.BytesIO(z.read(path))):
            if el.tag != f"{NS}row":
                continue
            cells: dict[int, object] = {}
            for c in el.iter(f"{NS}c"):
                kind = c.get("t", "n")
                v = c.find(f"{NS}v")
                if kind == "inlineStr":
                    cells[_col_index(c.get("r", "A1"))] = "".join(t.text or "" for t in c.iter(f"{NS}t"))
                    continue
                if v is None or v.text is None:
                    continue
                if kind == "s":
                    val: object = strings[int(v.text)]
                elif kind == "b":
                    val = v.text == "1"
                elif kind in ("str", "e"):
                    val = v.text
                else:
                    try:
                        val = float(v.text)
                    except ValueError:
                        val = v.text
                cells[_col_index(c.get("r", "A1"))] = val
            row_no = int(el.get("r", len(rows) + 1))
            while len(rows) < row_no - 1:  # rows Excel left out (all empty) keep their place
                rows.append([])
            rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
            el.clear()
            if max_rows and len(rows) >= max_rows:
                break
    except SyntaxError as e:  # ElementTree's ParseError is a SyntaxError
        raise XlsxError(f"BROKEN SHEET XML IN {name}") from e
    return rows


def excel_date(serial: object) -> date | None:
    """Excel's 1900 date system: serial 1 = 1900-01-01, with Excel's fake 1900-02-29 (so day 0 is 1899-12-30 for serials > 60)."""
    if not isinstance(serial, (int, float)) or serial < 61 or serial > 2958465:
        return None
    return date(1899, 12, 30) + timedelta(days=int(serial))


def trim_workbook(data: bytes, keep: list[str]) -> bytes:
    """A smaller workbook holding only the `keep` sheets (for test fixtures of large files). The other sheets' XML is dropped and
    workbook.xml lists only the kept sheets; shared strings are kept whole (indices must not move)."""
    z = _zip(data)
    keep_paths = {_sheet_path(z, n) for n in keep}
    wb = z.read("xl/workbook.xml").decode("utf-8")

    def keep_sheet(m: re.Match) -> str:
        nm = re.search(r'name="([^"]*)"', m.group(0))
        return m.group(0) if nm and nm.group(1).replace("&amp;", "&") in keep else ""

    wb = re.sub(r"<sheet [^>]*/>", keep_sheet, wb)
    wb = re.sub(r"<definedNames>.*?</definedNames>", "", wb, flags=re.DOTALL)  # names may point at dropped sheets
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for info in z.infolist():
            fn = info.filename
            if fn == "xl/workbook.xml":
                w.writestr(fn, wb)
            elif fn.startswith(("xl/worksheets/", "xl/chartsheets/", "xl/drawings/", "xl/charts/", "xl/calcChain")) and fn not in keep_paths:
                continue
            else:
                w.writestr(info, z.read(fn))
    return out.getvalue()
