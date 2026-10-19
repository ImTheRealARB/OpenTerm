"""`AI DOC`: text out of a file or filing, split into chunks, searched by keyword. Parsing is local (stdlib; PDF through pypdf).

A document lives only in memory (the last five), is never written to disk and is never sent anywhere except as the few chunks the model asks for.
"""

from __future__ import annotations

import io
import math
import re
import uuid
import zipfile
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree import ElementTree

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 3_000_000
CHUNK = 1500
OVERLAP = 150
KINDS = {"txt": "text", "md": "text", "json": "text", "csv": "csv", "htm": "html", "html": "html", "docx": "docx", "xlsx": "xlsx", "pdf": "pdf"}
BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "ul", "ol", "pre", "blockquote"}
WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "to", "for", "is", "are", "was", "were", "what", "how", "did", "do", "does", "by", "with", "at", "from", "that", "this"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))  # a newline inside a paragraph is only source formatting


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", ln).strip() for ln in "".join(p.out).split("\n"))
    return "\n".join(ln for ln in lines if ln)


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise ValueError("NOT A READABLE DOCX FILE") from e
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paras = ("".join(t.text or "" for t in p.iter(w + "t")) for p in root.iter(w + "p"))
    return "\n".join(p for p in paras if p.strip())


def _xlsx(data: bytes) -> str:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            strings = []
            if "xl/sharedStrings.xml" in names:
                sst = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
                strings = ["".join(t.text or "" for t in si.iter(ns + "t")) for si in sst.iter(ns + "si")]
            wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
            sheets = [(s.get("name") or f"Sheet{i}", s.get(rel + "id")) for i, s in enumerate(wb.iter(ns + "sheet"), 1)]
            out: list[str] = []
            for i, (name, _rid) in enumerate(sheets, 1):
                path = f"xl/worksheets/sheet{i}.xml"
                if path not in names:
                    continue
                out.append(f"Sheet {name}")
                for row in ElementTree.fromstring(z.read(path)).iter(ns + "row"):
                    vals = []
                    for c in row.iter(ns + "c"):
                        v = c.find(ns + "v")
                        if v is None or v.text is None:
                            continue
                        vals.append(strings[int(v.text)] if c.get("t") == "s" and int(v.text) < len(strings) else v.text)
                    if vals:
                        out.append(" | ".join(vals))
            return "\n".join(out)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError) as e:
        raise ValueError("NOT A READABLE XLSX FILE") from e


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("PDF NEEDS THE pypdf PACKAGE: uv sync") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("THE PDF IS ENCRYPTED")
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"NOT A READABLE PDF FILE: {type(e).__name__}") from e


def extract_text(name: str, data: bytes) -> tuple[str, str]:
    """-> (kind, text). Raises ValueError with a message fit for the screen."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    kind = KINDS.get(ext)
    if kind is None:
        raise ValueError(f"UNSUPPORTED FILE TYPE .{ext or '?'}: USE {' '.join('.' + k for k in KINDS)}")
    if kind == "docx":
        text = _docx(data)
    elif kind == "xlsx":
        text = _xlsx(data)
    elif kind == "pdf":
        text = _pdf(data)
    elif kind == "html":
        text = html_to_text(data.decode("utf-8", errors="replace"))
    else:
        text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise ValueError("THE FILE HAS NO TEXT (EMPTY, OR A SCANNED PDF: OCR IS NOT BUILT)")
    return kind, text[:MAX_CHARS].strip()


def chunk(text: str, size: int = CHUNK, overlap: int = OVERLAP) -> list[str]:
    """Pieces of about `size` characters cut at line ends, each starting with the last `overlap` characters of the one before."""
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > size:  # a very long line is cut on a space
            cut = line.rfind(" ", 0, size) or size
            cut = size if cut <= 0 else cut
            line, rest = line[:cut], line[cut:].lstrip()
            if cur and len(cur) + len(line) + 1 > size:
                out.append(cur)
                cur = cur[-overlap:] + "\n"
            cur += line + "\n"
            line = rest
        if cur and len(cur) + len(line) + 1 > size:
            out.append(cur.strip())
            cur = cur[-overlap:] + "\n"
        cur += line + "\n"
    if cur.strip():
        out.append(cur.strip())
    return out


def _terms(s: str) -> list[str]:
    return [w for w in WORD.findall(s.lower()) if w not in STOP]


def build_index(chunks: list[str]) -> list[tuple[Counter, int]]:
    """Per chunk: its term counts and its term total. Built once per document (about 170 ms for 3 million characters), not once per search."""
    out = []
    for c in chunks:
        terms = _terms(c)
        out.append((Counter(terms), len(terms)))
    return out


def search(chunks: list[str], query: str, k: int = 3, index: list[tuple[Counter, int]] | None = None) -> list[tuple[int, float]]:
    """(chunk index, score) best first: TF-IDF over query words. A query with no word in any chunk returns []."""
    q = _terms(query)
    if not q:
        return []
    docs = index if index is not None and len(index) == len(chunks) else build_index(chunks)
    n = len(docs)
    df = {w: sum(1 for d, _ in docs if w in d) for w in set(q)}
    scored = []
    for i, (d, total) in enumerate(docs):
        if not total:
            continue
        s = sum((1 + math.log(d[w])) * (math.log(1 + n / df[w])) for w in set(q) if df[w] and w in d)
        if s > 0:
            scored.append((i, s / math.sqrt(total)))
    return sorted(scored, key=lambda t: -t[1])[:k]


@dataclass
class Doc:
    id: str
    name: str
    kind: str
    chunks: list[str] = field(default_factory=list)
    _index: list[tuple[Counter, int]] | None = field(default=None, repr=False)

    def index(self) -> list[tuple[Counter, int]]:
        if self._index is None or len(self._index) != len(self.chunks):  # also rebuilt if the chunk list was edited
            self._index = build_index(self.chunks)
        return self._index

    @property
    def chars(self) -> int:
        return sum(len(c) for c in self.chunks)

    def card(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "chunks": len(self.chunks), "chars": self.chars, "preview": self.chunks[0][:240] if self.chunks else ""}


class DocStore:
    def __init__(self, cap: int = 5):
        self.cap = cap
        self.docs: OrderedDict[str, Doc] = OrderedDict()

    def add(self, name: str, kind: str, chunks: list[str]) -> Doc:
        return self.put(Doc(uuid.uuid4().hex[:8], name, kind, chunks))

    def put(self, d: Doc) -> Doc:
        self.docs[d.id] = d
        while len(self.docs) > self.cap:
            self.docs.popitem(last=False)
        return d

    def get(self, doc_id: str) -> Doc | None:
        return self.docs.get(doc_id)

    def __len__(self) -> int:
        return len(self.docs)


def doc_search(doc: Doc, query: str, k: int = 3) -> dict:
    hits = search(doc.chunks, query, max(1, min(k, 5)), doc.index())
    return {"source": doc.name, "document": doc.name, "chunks_in_document": len(doc.chunks),
            "matches": [{"chunk": f"C{i + 1}", "score": round(s, 3), "text": doc.chunks[i]} for i, s in hits]}
