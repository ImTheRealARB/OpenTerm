"""AI DOC OCR for scanned PDFs. Tesseract is optional: absent -> a clear next step; present -> pages are drawn with pypdfium2 and piped to it.
No test needs a real Tesseract: a tiny fake `tesseract` script stands in for it (the real one is exercised too when it is on PATH)."""

import io
import os
import shutil
import stat
import sys

import pytest
from test_phase16_agent import FakeGateway, call, sse, text

from openterm.ai import doc


@pytest.fixture
def renderer():
    """Tests that draw PDF pages need the optional extra (uv sync --extra ocr); the rest run in the default install."""
    return pytest.importorskip("pypdfium2", reason="optional OCR extra: uv sync --extra ocr")


def scanned_pdf(pages: int = 1) -> bytes:
    """A PDF whose pages carry no text layer (what a scan looks like to pypdf)."""
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(200, 100)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


@pytest.fixture
def no_tesseract(monkeypatch):
    monkeypatch.setattr(doc.shutil, "which", lambda name: None)


@pytest.fixture
def fake_tesseract(tmp_path, monkeypatch):
    """A script named `tesseract` first on PATH: reads the PGM from stdin and prints one line saying how big the page was."""
    exe = tmp_path / "bin" / "tesseract"
    exe.parent.mkdir()
    exe.write_text(f"#!{sys.executable}\nimport sys\nd = sys.stdin.buffer.read()\nassert d.startswith(b'P5')\nprint('Scanned revenue was 42 million, page of', len(d), 'bytes')\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])


def test_scanned_pdf_without_tesseract_says_how_to_install_it(no_tesseract):
    with pytest.raises(ValueError) as e:
        doc.extract_text("scan.pdf", scanned_pdf())
    msg = str(e.value)
    assert msg.startswith("OCR NOT INSTALLED") and "INSTALL TESSERACT" in msg and "OCR IS NOT BUILT" not in msg


def test_scanned_pdf_route_answers_400_with_the_next_step(client, no_tesseract):
    r = client.post("/api/ai/doc/upload?name=scan.pdf", content=scanned_pdf(), headers={"content-type": "application/octet-stream"})
    assert r.status_code == 400 and r.json()["error"].startswith("OCR NOT INSTALLED") and "TESSERACT" in r.json()["error"]


def test_ocr_text_is_labelled_and_tesseract_gets_every_page(fake_tesseract, renderer):
    kind, t = doc.extract_text("scan.pdf", scanned_pdf(pages=2))
    assert kind == "pdf" and t.startswith(doc.OCR_LABEL) and doc.OCR_LABEL == "OCR TEXT (MAY CONTAIN ERRORS)"
    assert t.count("Scanned revenue was 42 million") == 2


def test_a_pdf_with_a_text_layer_never_calls_ocr(no_tesseract):
    from test_phase16_doc import make_pdf

    _kind, t = doc.extract_text("p.pdf", make_pdf("Hello PDF world"))
    assert "Hello PDF world" in t and not t.startswith(doc.OCR_LABEL)


def test_missing_renderer_names_the_optional_extra(fake_tesseract, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)  # import raises ImportError
    with pytest.raises(ValueError, match="uv sync --extra ocr"):
        doc.extract_text("scan.pdf", scanned_pdf())


def test_tesseract_failure_and_empty_output_are_errors_not_empty_documents(tmp_path, renderer, monkeypatch):
    exe = tmp_path / "bin" / "tesseract"
    exe.parent.mkdir()
    exe.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.write('boom')\nsys.exit(3)\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])
    with pytest.raises(ValueError, match="TESSERACT FAILED ON PAGE 1: boom"):
        doc.extract_text("scan.pdf", scanned_pdf())
    exe.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.buffer.read()\n")
    with pytest.raises(ValueError, match="OCR FOUND NO TEXT"):
        doc.extract_text("scan.pdf", scanned_pdf())


def test_route_loads_an_ocr_document_and_the_model_is_told_it_is_ocr(client, fake_tesseract, renderer):
    r = client.post("/api/ai/doc/upload?name=scan.pdf", content=scanned_pdf(), headers={"content-type": "application/octet-stream"})
    card = r.json()["doc"]
    assert r.status_code == 200 and card["ocr"] is True and card["note"] == "OCR TEXT (MAY CONTAIN ERRORS)" and card["preview"].startswith("OCR TEXT")
    client.app.state.llm = FakeGateway(call("doc_search", {"query": "revenue"}), text("Revenue was 42 million (C1) [T1]."))
    ev = sse(client.post("/api/ai/doc/ask", json={"doc_id": card["id"], "question": "what was revenue?"}))
    assert ev[-1]["type"] == "done"
    system = client.app.state.llm.calls[0]["messages"][0]["content"]
    assert "read by OCR" in system and "recognition errors" in system


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed here")
def test_real_tesseract_reads_a_rendered_page(renderer):
    from pypdf import PdfReader  # noqa: F401 - the blank page has no text; a real scan needs an image PDF, so only check it does not crash

    with pytest.raises(ValueError, match="OCR FOUND NO TEXT"):
        doc.extract_text("blank.pdf", scanned_pdf())
