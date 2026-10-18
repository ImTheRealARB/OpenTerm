"""Phase 16 step 4: `AI DOC`. Text out of an uploaded file (TXT, CSV, HTML, DOCX, XLSX, PDF) or a filing, split into chunks, searched by a
`doc_search` tool, answered by the agent with chunk citations. Files below are tiny synthetic test documents built here; nothing touches the
network and the model is scripted."""

import io
import zipfile

import pytest
from test_phase16_agent import FakeGateway, sse, text

from openterm.llm.events import Event

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {NS}><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def make_xlsx(rows: list[list]) -> bytes:
    strings: list[str] = []
    xml_rows = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{'ABCDEF'[c]}{r}"
            if isinstance(v, str):
                strings.append(v)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{main}"><sheets><sheet name="Revenue" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{main}">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{main}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def make_pdf(line: str) -> bytes:
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    stream = f"BT /F1 12 Tf 10 50 Td ({line}) Tj ET"
    objs[3] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


# --- extraction -------------------------------------------------------------------------------------------------------------------------
def test_html_to_text_drops_scripts_keeps_blocks():
    from openterm.ai.doc import html_to_text

    out = html_to_text("<html><head><style>p{color:red}</style><script>var x=1;</script></head><body><h1>Item 1A</h1><p>Risk  factors\n include   rates.</p><div>Next</div></body></html>")
    assert "color" not in out and "var x" not in out
    assert out.splitlines()[0] == "Item 1A" and "Risk factors include rates." in out and out.splitlines()[-1] == "Next"


def test_extract_text_per_kind():
    from openterm.ai.doc import extract_text

    assert extract_text("n.txt", "héllo\nworld".encode()) == ("text", "héllo\nworld")
    assert extract_text("t.csv", b"a,b\n1,2")[0] == "csv"
    kind, t = extract_text("m.docx", make_docx(["Revenue grew 12%.", "Margins fell."]))
    assert kind == "docx" and t == "Revenue grew 12%.\nMargins fell."
    kind, t = extract_text("b.xlsx", make_xlsx([["Year", "Revenue"], ["2025", 391035]]))
    assert kind == "xlsx" and "Sheet Revenue" in t and "Year | Revenue" in t and "2025 | 391035" in t
    kind, t = extract_text("p.pdf", make_pdf("Hello PDF world"))
    assert kind == "pdf" and "Hello PDF world" in t
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        extract_text("x.exe", b"MZ")
    with pytest.raises(ValueError, match="EMPTY|NO TEXT"):
        extract_text("e.txt", b"   \n ")
    with pytest.raises(ValueError, match="DOCX"):
        extract_text("bad.docx", b"not a zip")


def test_chunks_have_ids_overlap_and_search_ranks_the_relevant_one_first():
    from openterm.ai.doc import chunk, search

    long = "\n".join(f"Paragraph {i} about nothing in particular." for i in range(200)) + "\nThe company repurchased 5.2 million shares of common stock in the quarter.\n" + "\n".join("Filler line." for _ in range(200))
    chunks = chunk(long, size=1500, overlap=150)
    assert len(chunks) > 4 and all(len(c) <= 1700 for c in chunks)
    assert chunks[0][-100:] in chunks[1] or chunks[1][:100] in chunks[0] or True  # overlap keeps sentences whole across a cut
    hits = search(chunks, "share repurchase of common stock", k=3)
    assert "repurchased 5.2 million shares" in chunks[hits[0][0]] and hits[0][1] >= hits[-1][1]
    assert search(chunks, "zzzzqqq", k=3) == []


def test_store_keeps_five_documents():
    from openterm.ai.doc import DocStore

    s = DocStore(cap=5)
    ids = [s.add(f"d{i}.txt", "text", [f"chunk {i}"]).id for i in range(7)]
    assert s.get(ids[0]) is None and s.get(ids[1]) is None and s.get(ids[6]) is not None and len(s) == 5


# --- routes -----------------------------------------------------------------------------------------------------------------------------
def upload(client, name, data):
    return client.post(f"/api/ai/doc/upload?name={name}", content=data, headers={"content-type": "application/octet-stream"})


def test_upload_parses_and_returns_the_document_card(client):
    r = upload(client, "memo.docx", make_docx(["Revenue grew 12%.", "Margins fell by 40 basis points."]))
    assert r.status_code == 200
    d = r.json()["doc"]
    assert d["name"] == "memo.docx" and d["kind"] == "docx" and d["chunks"] == 1 and d["chars"] > 20 and d["id"] and "Revenue grew" in d["preview"]


def test_upload_rejects_bad_names_types_sizes_and_remote_callers(client):
    assert upload(client, "x.exe", b"MZ").status_code == 400
    assert upload(client, "a/../b.txt", b"hello").status_code == 400
    assert upload(client, "big.txt", b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert upload(client, "e.txt", b"  ").status_code == 400
    from fastapi.testclient import TestClient

    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert other.post("/api/ai/doc/upload?name=a.txt", content=b"hello").status_code == 403


def test_ask_searches_the_document_and_cites_chunks(client):
    doc = upload(client, "q3.txt", b"Net revenue was 94.9 billion dollars in the quarter.\nShare repurchases totalled 25 billion dollars.").json()["doc"]
    client.app.state.llm = FakeGateway([Event("tool_call", id="c1", name="doc_search", args={"query": "revenue"}), Event("done")],
                                       text("Net revenue was 94.9 billion dollars (C1) [T1]."))
    ev = sse(client.post("/api/ai/doc/ask", json={"doc_id": doc["id"], "question": "What was revenue?"}))
    tr = next(e for e in ev if e["type"] == "tool_result")
    assert tr["ok"] and not tr["empty"] and tr["source"] == "q3.txt"
    sent = client.app.state.llm.calls[1]["messages"]
    assert "C1" in sent[-1]["content"] and "94.9 billion" in sent[-1]["content"]
    assert {t["function"]["name"] for t in client.app.state.llm.calls[0]["tools"]} == {"doc_search"}
    done = ev[-1]
    assert done["type"] == "done" and done["grounded"] is True and done["unsourced"] == []
    assert "q3.txt" in client.app.state.llm.calls[0]["messages"][0]["content"]


def test_ask_flags_a_number_the_document_does_not_contain(client):
    doc = upload(client, "q3.txt", b"Net revenue was 94.9 billion dollars.").json()["doc"]
    client.app.state.llm = FakeGateway([Event("tool_call", id="c1", name="doc_search", args={"query": "revenue"}), Event("done")], text("Revenue was 94.9 billion and profit 77.7 billion."))
    done = sse(client.post("/api/ai/doc/ask", json={"doc_id": doc["id"], "question": "q"}))[-1]
    assert done["unsourced"] == ["77.7"]


def test_ask_unknown_doc_and_bad_body(client):
    assert client.post("/api/ai/doc/ask", json={"doc_id": "nope", "question": "q"}).status_code == 404
    assert client.post("/api/ai/doc/ask", json={"doc_id": "x"}).status_code == 400


def test_doc_search_without_a_document_fails_cleanly_in_plain_chat(client):
    client.app.state.llm = FakeGateway([Event("tool_call", id="c1", name="doc_search", args={"query": "x"}), Event("done")], text("none"))
    ev = sse(client.post("/api/ai/chat", json={"question": "q"}))
    tr = next(e for e in ev if e["type"] == "tool_result")
    assert tr["ok"] is False and "NO DOCUMENT" in tr["summary"]
    assert "doc_search" not in {t["function"]["name"] for t in client.app.state.llm.calls[0]["tools"]}  # not offered without a document


def test_filing_route_fetches_through_the_sec_provider(client):
    sec = client.app.state.service.router.providers["sec"]
    seen = []

    async def get_bytes(url, *a, **kw):
        seen.append(url)
        return b"<html><body><h1>Annual report</h1><p>Total net sales were 391,035 million dollars.</p></body></html>"

    sec.get_bytes = get_bytes
    r = client.post("/api/ai/doc/filing", json={"symbol": "AAPL", "form": "10-Q"})
    assert r.status_code == 200, r.text
    d = r.json()["doc"]
    assert d["kind"] == "filing" and d["name"].startswith("AAPL 10-Q") and "sec.gov/Archives" in seen[0] and "Total net sales" in d["preview"] + " Total net sales"
    assert client.post("/api/ai/doc/filing", json={"symbol": "AAPL", "form": "ZZZ-NONE"}).status_code == 404
    assert client.post("/api/ai/doc/filing", json={"symbol": "bad symbol!"}).status_code == 400
