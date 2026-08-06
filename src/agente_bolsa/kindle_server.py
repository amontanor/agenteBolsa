"""Independent, server-rendered, read-only Kindle page."""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .tools.kindle_snapshot import DEFAULT_RELATIVE_PATH, read_kindle_snapshot

MADRID = ZoneInfo("Europe/Madrid")


def _number(value: Any, *, percent: bool = False) -> str:
    if value is None or isinstance(value, bool):
        return "n/d"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/d"
    if percent:
        return f"{number:+.2%}"
    return f"{number:+,.2f}"


def _plain_number(value: Any, decimals: int = 4) -> str:
    if value is None or isinstance(value, bool):
        return "n/d"
    try:
        return f"{float(value):,.{decimals}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "n/d"


def _date_time(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(MADRID).strftime("%d/%m/%Y %H:%M %Z")
    except (TypeError, ValueError):
        return "n/d"


def _age_seconds(value: Any, now: datetime | None = None) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        age = (current.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
        return max(0.0, age)
    except (TypeError, ValueError):
        return None


def render_kindle_page(snapshot: dict[str, Any] | None, *, now: datetime | None = None) -> str:
    """Render the intentionally narrow Kindle contract with escaped values."""

    data = snapshot or {}
    portfolio = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else {}
    benchmark = data.get("benchmark") if isinstance(data.get("benchmark"), dict) else {}
    captured_at = data.get("as_of") or data.get("captured_at")
    age = _age_seconds(captured_at, now=now)
    fresh = (
        f"Datos con {int(age // 60)} min de antigüedad"
        if age is not None and age >= 60
        else "Datos recién capturados"
        if age is not None
        else "Snapshot no disponible"
    )
    portfolio_status = str(portfolio.get("status") or "unavailable")
    today_value = _number(portfolio.get("amount")) if portfolio_status == "available" else "n/d"
    today_pct = _number(portfolio.get("pct"), percent=True) if portfolio_status == "available" else "n/d"
    benchmark_status = str(benchmark.get("status") or "unavailable")
    spy_value = _number(benchmark.get("pct"), percent=True) if benchmark_status == "comparable" else "n/d"
    spy_note = (
        "Ventana comparable al as_of"
        if benchmark_status == "comparable"
        else f"n/d — {html.escape(str(benchmark.get('reason') or 'no comparable'))}"
    )
    rows = []
    for position in data.get("positions") or []:
        if not isinstance(position, dict):
            continue
        rows.append(
            "<tr>"
            f"<th scope=\"row\">{html.escape(str(position.get('symbol') or 'n/d'))}</th>"
            f"<td>{html.escape(_plain_number(position.get('qty')))}</td>"
            f"<td>{html.escape(_plain_number(position.get('avg_entry_price'), 2))}</td>"
            f"<td>{html.escape(_plain_number(position.get('current_price'), 2))}</td>"
            f"<td>{html.escape(_number(position.get('total_pl_pct'), percent=True))}</td>"
            f"<td>{html.escape(_number(position.get('today_pl_pct'), percent=True))}</td>"
            "</tr>"
        )
    position_body = "".join(rows) or '<tr><td colspan="6">Sin posiciones disponibles</td></tr>'
    as_of_label = html.escape(_date_time(captured_at))
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Cartera</title>
<style>
html {{ background:#fff; color:#000; }} body {{ margin:1.2rem auto; max-width:42rem; padding:0 1rem; font:1.05rem/1.45 system-ui,sans-serif; }}
h1 {{ font-size:1.55rem; margin:0; }} h2 {{ border-bottom:2px solid #000; font-size:1.1rem; margin:1.4rem 0 .5rem; padding-bottom:.2rem; }}
.stamp {{ margin:.15rem 0 1.1rem; }} .metric {{ font-size:1.5rem; font-weight:700; margin:.2rem 0; }}
.note {{ font-size:.9rem; margin:.2rem 0; }} table {{ border-collapse:collapse; width:100%; }} th,td {{ border-bottom:1px solid #777; padding:.45rem .25rem; text-align:right; white-space:nowrap; }} th:first-child,td:first-child {{ text-align:left; }}
a {{ color:#000; font-weight:700; }} @media (max-width:34rem) {{ body {{ font-size:.92rem; margin:.7rem auto; padding:0 .55rem; }} th,td {{ padding:.35rem .12rem; }} .metric {{ font-size:1.25rem; }} }}
</style></head><body>
<header><h1>Cartera</h1><p class="stamp">Actualizado {as_of_label}<br>{html.escape(fresh)}</p></header>
<main>
<section aria-labelledby="today"><h2 id="today">Ganancia/pérdida global de hoy</h2>
<p class="metric">{html.escape(today_value)} USD ({html.escape(today_pct)})</p>
<p class="note">Equity actual − cierre XNYS anterior · fuente account.last_equity</p></section>
<section aria-labelledby="spy"><h2 id="spy">S&amp;P 500 de hoy</h2>
<p class="metric">{html.escape(spy_value)}</p><p class="note">{spy_note}</p></section>
<section aria-labelledby="positions"><h2 id="positions">Posiciones</h2>
<table><thead><tr><th scope="col">Símbolo</th><th scope="col">Cantidad</th><th scope="col">Entrada</th><th scope="col">Actual</th><th scope="col">P/L total</th><th scope="col">P/L hoy</th></tr></thead>
<tbody>{position_body}</tbody></table></section>
<p class="note"><a href="/kindle">Actualizar</a></p>
</main></body></html>"""


class KindleRequestHandler(BaseHTTPRequestHandler):
    server_version = "AgenteBolsaKindle/1"

    @property
    def snapshot_file(self) -> Path:
        return Path(self.server.snapshot_file)

    def _send(self, status: HTTPStatus, content_type: str, body: bytes = b"") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        path = urlsplit(self.path).path
        if path == "/kindle":
            body = render_kindle_page(read_kindle_snapshot(self.snapshot_file)).encode("utf-8")
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", body)
            return
        if path == "/health":
            snapshot = read_kindle_snapshot(self.snapshot_file)
            body = json.dumps({"ok": True, "service": "kindle", "snapshot_available": snapshot is not None}).encode("utf-8")
            self._send(HTTPStatus.OK, "application/json; charset=utf-8", body)
            return
        self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found")

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API.
        self.do_GET()

    def _method_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def run_server(*, host: str, port: int, snapshot_file: str | Path) -> None:
    server = ThreadingHTTPServer((host, port), KindleRequestHandler)
    server.snapshot_file = Path(snapshot_file).resolve()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor Kindle read-only de agenteBolsa.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--snapshot", default=str(DEFAULT_RELATIVE_PATH))
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, snapshot_file=args.snapshot)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
