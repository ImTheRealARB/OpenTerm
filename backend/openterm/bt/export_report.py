"""BT EXPORT as a PDF report (fpdf2) or an XLSX workbook (xlsxwriter) of a stored run. Both are built from the stored
run only (nothing is recomputed, nothing is fetched) and carry the HISTORICAL SIMULATION label. Blocking and CPU-bound:
the API calls these through `asyncio.to_thread`. Text cells are neutralised against spreadsheet formulas like the CSV export.
"""

from __future__ import annotations

import datetime as dt
import io
import itertools
import json

from .export import TRADE_FIELDS, neutralize
from .job import HEADLINE

PDF_TYPE = "application/pdf"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEETS = ("Summary", "Equity", "Trades", "Parameters")


def _day(t) -> str:
    return dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%d")


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, dict | list | tuple):
        return json.dumps(v, sort_keys=True, default=str)
    return str(v)


def scalar_metrics(run: dict) -> list[tuple[str, object]]:
    return [(k, v) for k, v in run["metrics"].items() if not isinstance(v, dict | list)]


def parameter_rows(run: dict) -> list[tuple[str, str]]:
    """Everything that defines the run, as (name, text) pairs: strategy, universe, options, costs, data sources."""
    lab, cfg = run.get("labels") or {}, run.get("config") or {}
    rows: list[tuple[str, str]] = [("run id (content hash)", run["id"]), ("engine", run.get("engine") or lab.get("engine")),
                                   ("rule", run.get("rule")), ("python strategy", run.get("strategy")),
                                   ("symbols", ", ".join(run.get("symbols") or [])), ("interval", run.get("interval")),
                                   ("range", run.get("range")), ("short selling", lab.get("short")),
                                   ("prices", lab.get("prices")), ("fees (bps)", lab.get("fees_bps")),
                                   ("slippage (bps)", lab.get("slip_bps")), ("cost model", lab.get("costs")),
                                   ("warmup bars", lab.get("warmup_bars")), ("benchmark", lab.get("benchmark")),
                                   ("data note", lab.get("data_note")), ("model", lab.get("model"))]
    for s in lab.get("sources") or []:
        rows.append((f"data source {s.get('symbol')}", f"{s.get('name')} as of {s.get('as_of')}"
                     + (" STALE" if s.get("stale") else "")))
    rows += [(f"config.{k}", v) for k, v in sorted(cfg.items())]
    return [(k, _text(v)) for k, v in rows if v not in (None, "")]


def trade_summary(run: dict) -> dict:
    tr = run["trades"]
    pnl = [t["pnl"] for t in tr if isinstance(t.get("pnl"), int | float)]
    wins = [p for p in pnl if p > 0]
    return {"trades": len(tr), "with pnl": len(pnl), "winners": len(wins), "losers": sum(1 for p in pnl if p < 0),
            "win rate": (len(wins) / len(pnl)) if pnl else None, "total pnl": sum(pnl) if pnl else None,
            "best trade": max(pnl) if pnl else None, "worst trade": min(pnl) if pnl else None}


def _drawdown(eq: list[float]) -> list[float]:
    peak, out = float("-inf"), []
    for v in eq:
        peak = max(peak, v)
        out.append(v / peak - 1.0 if peak else 0.0)
    return out


# --- XLSX -----------------------------------------------------------------------------------------------------------------

def run_xlsx(run: dict) -> bytes:
    import xlsxwriter

    buf = io.BytesIO()
    # strings_to_formulas / urls off: a text cell is never parsed as a formula or link; neutralize() adds the second guard.
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False,
                                   "strings_to_numbers": False})
    bold = wb.add_format({"bold": True})
    cell = lambda ws, r, c, v: ws.write(r, c, "" if v is None else neutralize(v) if isinstance(v, str) else v)

    def table(name: str, header: list[str], rows: list[list], widths: list[int]):
        ws = wb.add_worksheet(name)
        for c, h in enumerate(header):
            ws.write(0, c, h, bold)
            ws.set_column(c, c, widths[c])
        for r, row in enumerate(rows, 1):
            for c, v in enumerate(row):
                cell(ws, r, c, v)
        ws.freeze_panes(1, 0)
        return ws

    summary: list[list] = [["notice", HEADLINE], ["run id", run["id"]], ["created (UTC)", _day(run["created_at"]) if run.get("created_at") else ""]]
    summary += [[f"metric: {k}", v] for k, v in scalar_metrics(run)]
    summary += [[f"trades: {k}", v] for k, v in trade_summary(run).items()]
    table("Summary", ["item", "value"], summary, [34, 40])
    bench = {t: v for t, v in run.get("benchmark") or []}
    table("Equity", ["date", "equity", "benchmark"], [[_day(t), v, bench.get(t)] for t, v in run["equity"]], [14, 16, 16])
    table("Trades", list(TRADE_FIELDS), [[t.get(k) for k in TRADE_FIELDS] for t in run["trades"]], [14] * len(TRADE_FIELDS))
    table("Parameters", ["parameter", "value"], [[k, v] for k, v in parameter_rows(run)], [30, 70])
    wb.close()
    return buf.getvalue()


# --- PDF ------------------------------------------------------------------------------------------------------------------

def _latin(s) -> str:
    """The built-in PDF fonts are Latin-1 only: anything else becomes '?', never an exception."""
    return _text(s).encode("latin-1", "replace").decode("latin-1")


def _fmt(v) -> str:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return _latin(v)
    if isinstance(v, int) or abs(v) >= 1000:
        return f"{v:,.0f}" if abs(v) >= 1000 else str(v)
    return f"{v:.4f}".rstrip("0").rstrip(".") if v else "0"


def run_pdf(run: dict) -> bytes:
    from fpdf import FPDF

    class Report(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "B", 7)
            self.cell(0, 5, f"{HEADLINE}  |  run {run['id']}  |  page {self.page_no()}/{{nb}}", align="C")

    pdf = Report(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_title(_latin(f"OpenTerm BT report {run['id']}"))
    pdf.set_creator("OpenTerm")
    pdf.alias_nb_pages()
    pdf.add_page()
    W = pdf.w - pdf.l_margin - pdf.r_margin

    def h(txt):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _latin(txt), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)

    def kv(rows, col=62):
        for k, v in rows:
            pdf.set_x(pdf.l_margin)
            pdf.cell(col, 4.6, _latin(k)[:48], border="B")
            pdf.multi_cell(W - col, 4.6, _fmt(v)[:300], border="B", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, "OpenTerm backtest report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(160, 30, 30)
    pdf.cell(0, 6, HEADLINE, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(0, 4.2, _latin(
        f"Run {run['id']} (content hash of the strategy, options and data) | "
        f"{', '.join(run.get('symbols') or [])} {run.get('interval') or ''} {run.get('range') or ''} | "
        f"{run.get('rule') or run.get('strategy') or 'strategy code'}"), new_x="LMARGIN", new_y="NEXT")

    def chart(title, series, height, fmt):
        h(title)
        x0, y0, w = pdf.l_margin, pdf.get_y() + 1, W
        pdf.set_draw_color(180)
        pdf.rect(x0, y0, w, height)
        for name, pts, rgb in series:
            if len(pts) < 2:
                continue
            lo, hi = min(min(p) for _, p, _ in series if len(p) > 1), max(max(p) for _, p, _ in series if len(p) > 1)
            span = (hi - lo) or 1.0
            pdf.set_draw_color(*rgb)
            pdf.set_line_width(0.3)
            step = max(1, len(pts) // 600)
            idx = list(range(0, len(pts), step)) + ([len(pts) - 1] if (len(pts) - 1) % step else [])
            xy = [(x0 + w * i / (len(pts) - 1), y0 + height - height * (pts[i] - lo) / span) for i in idx]
            for (xa, ya), (xb, yb) in itertools.pairwise(xy):
                pdf.line(xa, ya, xb, yb)
        pdf.set_line_width(0.2)
        pdf.set_draw_color(0)
        vals = [v for _, p, _ in series for v in p]
        if vals:
            pdf.set_font("Helvetica", "", 7)
            pdf.set_xy(x0 + 1, y0 + 0.5)
            pdf.cell(60, 3.5, f"max {fmt(max(vals))}")
            pdf.set_xy(x0 + 1, y0 + height - 4)
            pdf.cell(60, 3.5, f"min {fmt(min(vals))}   " + "   ".join(n for n, p, _ in series if len(p) > 1))
        pdf.set_y(y0 + height + 1)
        pdf.set_font("Helvetica", "", 8)

    eq = [v for _, v in run["equity"]]
    bench = [v for _, v in run.get("benchmark") or []]
    if len(eq) >= 2:
        span = f"{_day(run['equity'][0][0])} to {_day(run['equity'][-1][0])}"
        chart(f"Equity curve ({span}); blue = strategy, grey = benchmark", [("strategy", eq, (30, 80, 170)),
              ("benchmark", bench if len(bench) == len(eq) else [], (140, 140, 140))], 50, lambda v: f"{v:,.0f}")
        chart("Drawdown from the running peak", [("drawdown", _drawdown(eq), (170, 40, 40))], 28, lambda v: f"{v:.1%}")
    else:
        h("Equity curve")
        pdf.cell(0, 5, "NO EQUITY CURVE STORED FOR THIS RUN", new_x="LMARGIN", new_y="NEXT")

    h("Metrics")
    kv(scalar_metrics(run))
    h("Trades summary")
    kv(list(trade_summary(run).items()))
    tr = run["trades"]
    if tr:
        cols = ("symbol", "direction", "entry_time", "exit_time", "pnl", "pnl_pct", "exit_reason")
        widths = [34, 16, 28, 28, 24, 20, W - 150]
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 7)
        for c, w in zip(cols, widths, strict=True):
            pdf.cell(w, 4.4, c, border="B")
        pdf.ln()
        pdf.set_font("Helvetica", "", 7)
        for t in tr[:40]:
            for c, w in zip(cols, widths, strict=True):
                pdf.cell(w, 4.2, _fmt(t.get(c))[:22])
            pdf.ln()
        if len(tr) > 40:
            pdf.cell(0, 4.4, f"... {len(tr) - 40} more trades: use the TRADES CSV or XLSX export", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
    h("Parameters, data source, fees and slippage")
    kv(parameter_rows(run))
    h("Notice")
    pdf.multi_cell(0, 4.2, _latin(
        f"{HEADLINE}. Past results do not predict future ones. Fills, fees and slippage follow the models listed above and "
        "will differ from live trading. Generated by OpenTerm from the stored run; nothing here was recomputed."),
        new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
