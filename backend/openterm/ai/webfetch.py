"""Fetch one public web page for the AI, safely, and reduce it to readable text.

`safe_fetch` is the only place the AI touches the open internet. For every hop (the first request and each redirect, at most MAX_HOPS):
  1. the URL is checked (http or https, no user name or password, port 80 or 443 only);
  2. the host name is resolved HERE and every address must be public (see openterm.netguard);
  3. the request goes to that address, not to the name (the name only travels as the Host header and the TLS server name), so DNS cannot
     change its answer between the check and the connection (DNS rebinding);
  4. no cookie, credential or user detail is sent: a fixed generic User-Agent, cookies cleared after every hop, environment proxies ignored;
  5. only an allow-list of content types is read, at most MAX_BYTES of it, within a time limit.
"""

from __future__ import annotations

import asyncio
import io
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from .. import netguard

MAX_HOPS = 5
MAX_BYTES = 2_000_000
TIMEOUT_S = 15.0
TOTAL_TIMEOUT_S = 30.0
PDF_PAGES = 25
USER_AGENT = "Mozilla/5.0 (compatible; OpenTermReader/1.0)"
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown", "text/xml", "application/xml", "application/json", "application/pdf")
REDIRECTS = (301, 302, 303, 307, 308)


class FetchError(Exception):
    """Why a fetch did not produce text. The message is shown to the model, so it holds no secret and no page content."""


@dataclass
class Fetched:
    url: str  # the final URL after redirects
    content_type: str
    body: bytes
    truncated: bool
    hops: int
    raw_type: str = ""  # the Content-Type header as sent (for its charset)


def _pin(url: str, ip: netguard.IP) -> str:
    """The same URL with the checked address in place of the host name."""
    from urllib.parse import urlsplit, urlunsplit

    u = urlsplit(url)
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    return urlunsplit((u.scheme, f"{host}:{u.port}" if u.port else host, u.path or "/", u.query, ""))


async def _hop(client: httpx.AsyncClient, url: str, resolver) -> httpx.Response:
    """One request, streamed (the body is not read yet), to an address that was checked."""
    _scheme, host, port = netguard.check_public_url(url)
    ips = await netguard.public_addresses(host, port, resolver)
    last: Exception | None = None
    for ip in ips[:3]:  # every address was checked; try the next one only when this one does not connect
        req = client.build_request("GET", _pin(url, ip), headers={"Host": host if port in (80, 443) else f"{host}:{port}", "User-Agent": USER_AGENT,
                                                                 "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.8,*/*;q=0.1",
                                                                 "Accept-Encoding": "gzip"},
                                   extensions={"sni_hostname": host})
        try:
            resp = await client.send(req, stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            last = e
            continue
        client.cookies.clear()  # a Set-Cookie must never come back on a later hop
        return resp
    raise FetchError(f"COULD NOT CONNECT ({type(last).__name__ if last else 'NO ADDRESS'})")


async def safe_fetch(url: str, *, client: httpx.AsyncClient | None = None, resolver=None, max_bytes: int = MAX_BYTES) -> Fetched:
    """GET `url` with every defence above. Raises FetchError (or netguard.Blocked, a ValueError) with a message for the model."""
    own = client is None
    http = client or httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(TIMEOUT_S), max_redirects=0,
                                       limits=httpx.Limits(max_connections=2))
    deadline = time.monotonic() + TOTAL_TIMEOUT_S
    try:
        current = url.strip()
        for hop in range(MAX_HOPS + 1):
            try:
                async with asyncio.timeout(max(1.0, deadline - time.monotonic())):
                    resp = await _hop(http, current, resolver)
                    try:
                        if resp.status_code in REDIRECTS:
                            loc = resp.headers.get("location")
                            if not loc:
                                raise FetchError("REDIRECT WITHOUT A LOCATION")
                            nxt = urljoin(current, loc.strip())
                            if hop >= MAX_HOPS:
                                raise FetchError(f"MORE THAN {MAX_HOPS} REDIRECTS")
                            if current.startswith("https://") and nxt.lower().startswith("http://"):
                                raise FetchError("REDIRECT FROM https TO http REFUSED")
                            current = nxt  # re-checked at the top of the next hop: scheme, port, DNS, every address
                            continue
                        if resp.status_code != 200:
                            raise FetchError(f"THE SERVER ANSWERED HTTP {resp.status_code}")
                        ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if ctype not in ALLOWED_TYPES:
                            raise FetchError(f"CONTENT TYPE {ctype[:60] or 'UNKNOWN'} IS NOT READABLE (ALLOWED: HTML, TEXT, JSON, XML, PDF)")
                        chunks, size, truncated = [], 0, False
                        async for part in resp.aiter_bytes():
                            size += len(part)
                            if size > max_bytes:
                                chunks.append(part[: len(part) - (size - max_bytes)])
                                truncated = True
                                break
                            chunks.append(part)
                        return Fetched(current, ctype, b"".join(chunks), truncated, hop, resp.headers.get("content-type", ""))
                    finally:
                        await resp.aclose()
            except TimeoutError:
                raise FetchError("THE PAGE TOOK TOO LONG") from None
            except httpx.HTTPError as e:
                raise FetchError(f"NETWORK ERROR ({type(e).__name__})") from None
        raise FetchError(f"MORE THAN {MAX_HOPS} REDIRECTS")
    finally:
        if own:
            await http.aclose()


# --- text extraction -------------------------------------------------------------------------------------------------------------------
SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed", "head", "nav", "footer", "aside", "form", "button",
        "select", "dialog", "menu", "audio", "video", "map"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "main", "blockquote", "pre", "hr",
         "header", "figure", "figcaption", "dd", "dt", "dl", "td", "th"}
HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(?![.\d])", re.IGNORECASE)


class _Text(HTMLParser):
    """Visible text only: scripts, styles, navigation, forms, comments and elements hidden from the reader are dropped (a favourite place to hide
    instructions for a model). Text inside <main> or <article> is kept apart and preferred when there is enough of it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.all: list[str] = []
        self.main: list[str] = []
        self.skip = 0
        self.main_depth = 0
        self.in_title = False
        self.stack: list[tuple[str, bool, bool]] = []  # (tag, skipped, main)

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            if tag in BLOCK:
                self._put("\n")
            return
        a = dict(attrs)
        hidden = "hidden" in a or a.get("aria-hidden") == "true" or bool(HIDDEN_STYLE.search(a.get("style") or ""))
        skipped = tag in SKIP or hidden
        is_main = tag in ("main", "article")
        self.stack.append((tag, skipped, is_main))
        self.skip += skipped
        self.main_depth += is_main
        if tag == "title":
            self.in_title = True
        if tag in BLOCK:
            self._put("\n")

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):  # close back to the matching tag; unclosed inner tags close with it
            if self.stack[i][0] == tag:
                for t, sk, mn in reversed(self.stack[i:]):
                    self.skip -= sk
                    self.main_depth -= mn
                del self.stack[i:]
                break
        if tag == "title":
            self.in_title = False
        if tag in BLOCK:
            self._put("\n")

    def handle_data(self, data):
        if self.in_title and not self.title:
            self.title = " ".join(data.split())[:200]
        self._put(data)

    def _put(self, s: str) -> None:
        if self.skip or self.in_title:
            return
        self.all.append(s)
        if self.main_depth:
            self.main.append(s)


def _tidy(parts: list[str]) -> str:
    text = "".join(parts)
    text = re.sub(r"[ \t\r\f\v ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_text(html: str) -> tuple[str, str]:
    """(title, text)."""
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001, S110 - HTMLParser can raise on broken markup; what was read so far is still usable
        pass
    main, whole = _tidy(p.main), _tidy(p.all)
    return p.title, main if len(main) >= 400 else whole


def pdf_to_text(data: bytes) -> tuple[str, str]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise FetchError("THE PDF IS ENCRYPTED")
        pages = [(p.extract_text() or "") for p in reader.pages[:PDF_PAGES]]
        title = str((reader.metadata or {}).get("/Title") or "")[:200]
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001 - a broken or hostile PDF: the type only
        raise FetchError(f"THE PDF COULD NOT BE READ ({type(e).__name__})") from None
    return title, _tidy(["\n\n".join(pages)])


def _charset(ctype_header: str, data: bytes) -> str:
    m = re.search(r"charset=([\w\-]+)", ctype_header or "", re.IGNORECASE) or re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", data[:2048], re.IGNORECASE)
    if m:
        v = m.group(1)
        return v.decode("ascii", "ignore") if isinstance(v, bytes) else v
    return "utf-8"


def extract(f: Fetched) -> tuple[str, str]:
    """(title, readable text) of a fetched document."""
    if f.content_type == "application/pdf":
        if f.truncated:
            raise FetchError(f"THE PDF IS LARGER THAN {MAX_BYTES // 1_000_000} MB")
        return pdf_to_text(f.body)
    enc = _charset(f.raw_type, f.body)
    try:
        s = f.body.decode(enc, errors="replace")
    except LookupError:
        s = f.body.decode("utf-8", errors="replace")
    if f.content_type in ("text/html", "application/xhtml+xml"):
        return html_to_text(s)
    return "", _tidy([s])
