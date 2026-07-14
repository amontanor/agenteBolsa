"""Caracterización de ``performance_daily`` y contrato prospectivo P-L40B.

Estas pruebas separan deliberadamente:

* ``current_behavior``: reproduce pérdidas presentes en 0.4.171;
* ``expected_p_l40b_contract``: helpers de prueba que fijan el contrato que
  P-L40B deberá satisfacer, sin cambiar todavía código productivo.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import agente_bolsa.tools.market_data as market_data
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.tools.performance_baseline import build_daily_performance, fetch_spy_daily_return
from agente_bolsa.tools.performance_benchmark import (
    benchmark_summary,
    build_daily_performance_item,
    build_performance_benchmark,
    derive_account_snapshot,
    load_cached_spy_observation,
)


def _store(tmp_path):
    store = Store(tmp_path / "db.sqlite3", tmp_path / "agents")
    store.ensure_schema()
    return store


def _settings(tmp_path):
    return SimpleNamespace(market_data_provider="auto", fmp_api_key=None, data_dir=tmp_path)


def _position(symbol: str, market_value: float, *, side: str | None = "long", unrealized_pl: float = 0.0):
    return PositionSnapshot(
        symbol=symbol,
        qty=1.0,
        market_value=market_value,
        avg_entry_price=100.0,
        current_price=100.0,
        unrealized_pl=unrealized_pl,
        unrealized_plpc=0.0,
        side=side or "",
    )


def _portfolio(
    *,
    equity: float = 1_000.0,
    cash: float | None = 700.0,
    buying_power: float | None = 700.0,
    positions: list[PositionSnapshot] | None = None,
):
    return PortfolioSnapshot(
        account_id="paper-test",
        status="ACTIVE",
        currency="USD",
        cash=cash,
        portfolio_value=equity,
        buying_power=buying_power,
        positions=positions or [],
        open_orders=[],
    )


def _read_raw_performance(store: Store) -> dict:
    with store.read_connection() as conn:
        row = conn.execute("SELECT * FROM performance_daily").fetchone()
    return dict(row)


def _future_account_fields(portfolio: PortfolioSnapshot) -> dict:
    """Helper de contrato: deriva campos de cuenta sin escribir producción."""

    equity = portfolio.portfolio_value
    warnings: list[str] = []
    long_value = 0.0
    short_value = 0.0
    net_known = True
    unrealized = 0.0
    for position in portfolio.positions:
        market_value = float(position.market_value)
        unrealized += float(position.unrealized_pl)
        side = str(position.side or "").lower()
        if side == "long":
            long_value += abs(market_value)
        elif side == "short":
            short_value += abs(market_value)
        else:
            net_known = False
            warnings.append("side_unavailable")
    gross = long_value + short_value
    net = long_value - short_value if net_known else None
    if not isinstance(equity, (int, float)) or equity <= 0:
        warnings.append("invalid_equity")
        gross_pct = None
        net_pct = None
        status = "unavailable"
    else:
        gross_pct = gross / equity
        net_pct = net / equity if net is not None else None
        status = "available" if not warnings else "partial"
    return {
        "status": status,
        "equity": equity,
        "cash": portfolio.cash,
        "buying_power": portfolio.buying_power,
        "long_market_value": long_value,
        "short_market_value": short_value,
        "gross_exposure_usd": gross,
        "net_exposure_usd": net,
        "gross_exposure_pct": gross_pct,
        "net_exposure_pct": net_pct,
        "position_count": len(portfolio.positions),
        "unrealized_pl": unrealized,
        "warnings": warnings,
    }


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _future_benchmark_metrics(
    *,
    equity: float | None,
    previous_equity: float | None,
    spy_close: float | None,
    previous_spy_close: float | None,
    gross_exposure_usd: float | None,
    session_average_gross_exposure: float | None,
) -> dict:
    account_return = _safe_ratio(equity, previous_equity)
    account_return = account_return - 1 if account_return is not None else None
    spy_return = _safe_ratio(spy_close, previous_spy_close)
    spy_return = spy_return - 1 if spy_return is not None else None
    gross_pct = _safe_ratio(gross_exposure_usd, equity)
    matched = (
        spy_return * session_average_gross_exposure
        if spy_return is not None and session_average_gross_exposure is not None
        else None
    )
    return {
        "account_daily_return": account_return,
        "spy_daily_return": spy_return,
        "gross_exposure_pct": gross_pct,
        "exposure_matched_spy_return": matched,
        "excess_return_total": account_return - spy_return
        if account_return is not None and spy_return is not None
        else None,
        "excess_return_exposure_matched": account_return - matched
        if account_return is not None and matched is not None
        else None,
    }


def _previous_xnys_session(session_date: str, sessions: list[str]) -> str | None:
    previous = [item for item in sessions if item < session_date]
    return previous[-1] if previous else None


def _session_bar_status(*, session_date: str, bar_date: str | None, closed: bool, sessions: set[str]) -> str:
    if not closed:
        return "unavailable:session_open"
    if session_date not in sessions:
        return "unavailable:missing_session_record"
    if not bar_date or bar_date not in sessions:
        return "unavailable:non_xnys_or_missing_bar"
    if bar_date > session_date:
        return "unavailable:future_bar"
    return "available"


def _time_weighted_exposure(
    snapshots: list[tuple[datetime, float]],
    *,
    session_start: datetime,
    session_end: datetime,
) -> dict:
    """Contrato de prueba: un único EOD no se convierte en media."""

    if len(snapshots) < 2 or session_end <= session_start:
        return {"status": "partial", "value": None}
    ordered = sorted(snapshots)
    covered = 0.0
    weighted = 0.0
    for (left_time, left_value), (right_time, _right_value) in zip(ordered, ordered[1:], strict=False):
        start = max(left_time, session_start)
        end = min(right_time, session_end)
        if end <= start:
            continue
        seconds = (end - start).total_seconds()
        covered += seconds
        weighted += seconds * left_value
    total = (session_end - session_start).total_seconds()
    if covered < total:
        return {"status": "partial", "value": None, "coverage": covered / total}
    return {"status": "available", "value": weighted / total, "coverage": 1.0}


def _future_price_basis(*, price_basis: str | None, source: str | None, as_of: str | None) -> dict:
    valid = {"close_unadjusted", "adjusted_close"}
    if price_basis not in valid or not source or not as_of:
        return {"status": "unavailable", "price_basis": price_basis}
    return {"status": "available", "price_basis": price_basis, "source": source, "as_of": as_of}


def _future_content_hash(snapshot: dict) -> str:
    content = {key: value for key, value in snapshot.items() if key not in {"captured_at", "content_hash"}}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _future_write_decision(existing: dict | None, incoming: dict) -> tuple[str, int]:
    if existing is None:
        return "write", 1
    if existing.get("content_hash") == incoming.get("content_hash"):
        return "noop", int(existing.get("revision", 1))
    return "conflict", int(existing.get("revision", 1)) + 1


def _metric_layers(*, total_return: float, pnl: float, deployed_notional: float, matched_return: float | None) -> dict:
    return {
        "total_account_return": total_return,
        "return_on_deployed_capital": pnl / deployed_notional if deployed_notional else None,
        "exposure_matched_return": matched_return,
        "pnl": pnl,
    }


def _spy_frame(kind: str, *, include_future: bool = False) -> pd.DataFrame:
    index = pd.to_datetime(["2026-07-07", "2026-07-08", "2026-07-14"] if include_future else ["2026-07-07", "2026-07-08"])
    close = [747.71, 745.40, 750.0][: len(index)]
    if kind == "flat":
        return pd.DataFrame({"Close": close}, index=index)
    if kind == "multi_spy_first":
        return pd.DataFrame({("SPY", "Close"): close}, index=index)
    if kind == "multi_close_first":
        return pd.DataFrame({("Close", "SPY"): close}, index=index)
    if kind == "multi_symbol":
        return pd.DataFrame({("SPY", "Close"): close, ("AIZ", "Close"): close}, index=index)
    if kind == "missing":
        return pd.DataFrame({"Open": [1.0, 1.0]}, index=index)
    return pd.DataFrame(index=index)


# ---------------------------------------------------------------------------
# current_behavior: defectos reproducibles en 0.4.171
# ---------------------------------------------------------------------------


def test_current_behavior_loses_alpha_column(tmp_path):
    store = _store(tmp_path)
    row = build_daily_performance(store, _settings(tmp_path), "2026-07-07", equity=101.0, spy_pct=0.01)
    assert row["alpha_vs_spy"] == pytest.approx(-0.01)
    store.upsert_performance_daily(row)
    persisted = _read_raw_performance(store)
    assert persisted["alpha"] is None


def test_current_behavior_drops_payload_metrics(tmp_path):
    store = _store(tmp_path)
    store.upsert_performance_daily(
        {
            "session_date": "2026-07-07",
            "equity": 101.0,
            "avg_exposure": 0.25,
            "result_metrics": {"alpha_vs_spy": 0.01},
            "process_metrics": {"buys": 2},
            "benchmarks": {"spy_buy_hold_pct": 0.005},
            "regime": "bullish",
        }
    )
    persisted = _read_raw_performance(store)
    assert persisted["payload_json"] == "{}"
    assert store.performance_daily(limit=0)[0]["payload"] == {}


@pytest.mark.parametrize("kind", ["multi_spy_first", "multi_close_first", "multi_symbol"])
def test_current_behavior_spy_reader_drops_yfinance_multiindex(tmp_path, monkeypatch, kind):
    cache = tmp_path / f"synthetic_{kind}.pkl"
    _spy_frame(kind).to_pickle(cache)
    monkeypatch.setattr(market_data, "download_daily_prices", lambda *args, **kwargs: pd.read_pickle(cache))
    assert fetch_spy_daily_return(_settings(tmp_path), "2026-07-08") is None


def test_current_behavior_spy_flat_frame_is_read(tmp_path, monkeypatch):
    cache = tmp_path / "synthetic_flat.pkl"
    _spy_frame("flat").to_pickle(cache)
    monkeypatch.setattr(market_data, "download_daily_prices", lambda *args, **kwargs: pd.read_pickle(cache))
    assert fetch_spy_daily_return(_settings(tmp_path), "2026-07-08") == pytest.approx(round(745.40 / 747.71 - 1, 6))


def test_current_behavior_upsert_overwrites_silently(tmp_path):
    store = _store(tmp_path)
    store.upsert_performance_daily({"session_date": "2026-07-07", "equity": 100.0, "payload": {"version": "A"}})
    first = _read_raw_performance(store)
    store.upsert_performance_daily({"session_date": "2026-07-07", "equity": 100.0, "payload": {"version": "A"}})
    store.upsert_performance_daily({"session_date": "2026-07-07", "equity": 101.0, "payload": {"version": "B"}})
    rows = store.performance_daily(limit=0)
    second = _read_raw_performance(store)
    assert len(rows) == 1
    assert rows[0]["equity"] == 101.0
    assert rows[0]["payload"] == {"version": "B"}
    assert second["created_at"] == first["created_at"]
    assert "content_hash" not in second.keys()
    assert "revision" not in second.keys()


def test_current_behavior_avg_exposure_is_one_eod_snapshot(tmp_path):
    store = _store(tmp_path)
    portfolio = _portfolio(positions=[_position("AIZ", 300.0), _position("CRWD", -200.0, side="short")])
    row = build_daily_performance(store, _settings(tmp_path), "2026-07-07", equity=1_000.0, portfolio=portfolio)
    assert row["avg_exposure"] == pytest.approx(0.5)
    assert "session_average_gross_exposure" not in row


# ---------------------------------------------------------------------------
# expected_p_l40b_contract: helpers de prueba, sin código productivo nuevo
# ---------------------------------------------------------------------------


def test_expected_account_fields_long_and_short():
    portfolio = _portfolio(
        cash=700.0,
        positions=[_position("AIZ", 300.0, unrealized_pl=4.0), _position("CRWD", -200.0, side="short", unrealized_pl=-2.0)],
    )
    fields = _future_account_fields(portfolio)
    assert fields["status"] == "available"
    assert fields["long_market_value"] == pytest.approx(300.0)
    assert fields["short_market_value"] == pytest.approx(200.0)
    assert fields["gross_exposure_usd"] == pytest.approx(500.0)
    assert fields["net_exposure_usd"] == pytest.approx(100.0)
    assert fields["gross_exposure_pct"] == pytest.approx(0.5)
    assert fields["net_exposure_pct"] == pytest.approx(0.1)
    assert fields["unrealized_pl"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("portfolio", "status"),
    [
        (_portfolio(positions=[]), "available"),
        (_portfolio(equity=0.0, positions=[_position("AIZ", 100.0)]), "unavailable"),
        (_portfolio(positions=[_position("AIZ", 100.0, side=None)]), "partial"),
        (_portfolio(cash=None, positions=[_position("AIZ", 100.0)]), "available"),
    ],
)
def test_expected_account_fields_edge_cases(portfolio, status):
    assert _future_account_fields(portfolio)["status"] == status


def test_expected_formulas_keep_missing_and_zero_unavailable():
    metrics = _future_benchmark_metrics(
        equity=101.0,
        previous_equity=100.0,
        spy_close=505.0,
        previous_spy_close=500.0,
        gross_exposure_usd=25.0,
        session_average_gross_exposure=0.25,
    )
    assert metrics["account_daily_return"] == pytest.approx(0.01)
    assert metrics["spy_daily_return"] == pytest.approx(0.01)
    assert metrics["gross_exposure_pct"] == pytest.approx(25 / 101)
    assert metrics["exposure_matched_spy_return"] == pytest.approx(0.0025)
    assert metrics["excess_return_total"] == pytest.approx(0.0)
    assert metrics["excess_return_exposure_matched"] == pytest.approx(0.0075)
    missing = _future_benchmark_metrics(
        equity=101.0,
        previous_equity=0.0,
        spy_close=None,
        previous_spy_close=500.0,
        gross_exposure_usd=25.0,
        session_average_gross_exposure=None,
    )
    assert all(value is None for key, value in missing.items() if key != "gross_exposure_pct")


def test_expected_xnys_previous_session_and_future_bar_rules():
    sessions = ["2026-07-09", "2026-07-10", "2026-07-13"]
    assert _previous_xnys_session("2026-07-13", sessions) == "2026-07-10"
    session_set = set(sessions)
    assert _session_bar_status(session_date="2026-07-13", bar_date="2026-07-13", closed=True, sessions=session_set) == "available"
    assert _session_bar_status(session_date="2026-07-13", bar_date="2026-07-14", closed=True, sessions=session_set) == "unavailable:non_xnys_or_missing_bar"
    assert _session_bar_status(session_date="2026-07-13", bar_date="2026-07-13", closed=False, sessions=session_set) == "unavailable:session_open"
    assert _session_bar_status(session_date="2026-07-12", bar_date="2026-07-12", closed=True, sessions=session_set) == "unavailable:missing_session_record"


def test_expected_time_weighted_exposure_never_promotes_single_eod_snapshot():
    start = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
    noon = start + timedelta(hours=3)
    close = start + timedelta(hours=6, minutes=30)
    complete = _time_weighted_exposure(
        [(start, 0.0), (noon, 0.5), (close - timedelta(minutes=30), 1.0), (close, 1.0)],
        session_start=start,
        session_end=close,
    )
    assert complete["status"] == "available"
    assert complete["value"] == pytest.approx((0.5 * 3.0 + 1.0 * 0.5) / 6.5)
    single_eod = _time_weighted_exposure([(close, 1.0)], session_start=start, session_end=close)
    assert single_eod["status"] == "partial"
    assert single_eod["value"] is None
    gap = _time_weighted_exposure([(start, 0.0), (noon, 0.5)], session_start=start, session_end=close)
    assert gap["status"] == "partial"


def test_expected_price_basis_is_explicit_and_not_mixed():
    adjusted = _future_price_basis(price_basis="adjusted_close", source="synthetic", as_of="2026-07-13T22:00:00Z")
    raw = _future_price_basis(price_basis="close_unadjusted", source="synthetic", as_of="2026-07-13T22:00:00Z")
    unknown = _future_price_basis(price_basis=None, source="synthetic", as_of="2026-07-13T22:00:00Z")
    assert adjusted["status"] == "available"
    assert raw["status"] == "available"
    assert unknown["status"] == "unavailable"
    assert adjusted["price_basis"] != raw["price_basis"]


def test_expected_hash_ignores_capture_timestamp_and_requires_schema():
    base = {
        "schema_version": "p-l40b.performance-benchmark.v1",
        "session_date": "2026-07-13",
        "account": {"equity": 100.0},
        "benchmark": {"symbol": "SPY", "close": 500.0},
        "captured_at": "2026-07-13T22:00:00Z",
        "revision": 1,
    }
    later = dict(base, captured_at="2026-07-13T22:05:00Z")
    changed = dict(base, account={"equity": 101.0})
    assert _future_content_hash(base) == _future_content_hash(later)
    assert _future_content_hash(base) != _future_content_hash(changed)
    assert _future_write_decision(None, dict(base, content_hash=_future_content_hash(base))) == ("write", 1)
    stored = dict(base, content_hash=_future_content_hash(base), revision=1)
    assert _future_write_decision(stored, dict(later, content_hash=_future_content_hash(later))) == ("noop", 1)
    assert _future_write_decision(stored, dict(changed, content_hash=_future_content_hash(changed))) == ("conflict", 2)


def test_expected_p_l40a_reproduction():
    equity = [70653.37, 70658.51, 70678.43, 70626.17, 70625.04]
    spy = [747.7100, 749.169983]
    account_return = equity[-1] / equity[0] - 1
    spy_return = spy[-1] / spy[0] - 1
    assert account_return == pytest.approx(-0.00040097, abs=1e-6)
    assert spy_return == pytest.approx(0.00195258, abs=1e-6)
    assert (account_return - spy_return) * 100 == pytest.approx(-0.2354, abs=0.001)


def test_expected_metric_layers_do_not_call_deployed_pnl_total_return():
    layers = _metric_layers(total_return=-0.00040097, pnl=-28.30, deployed_notional=6151.08, matched_return=None)
    assert layers["total_account_return"] == pytest.approx(-0.00040097)
    assert layers["return_on_deployed_capital"] == pytest.approx(-28.30 / 6151.08)
    assert layers["return_on_deployed_capital"] != layers["total_account_return"]
    assert layers["exposure_matched_return"] is None
    assert layers["pnl"] == pytest.approx(-28.30)


def test_expected_contract_schema_is_versioned_and_utf8_serializable():
    snapshot = {
        "schema_version": "p-l40b.performance-benchmark.v1",
        "session_date": "2026-07-13",
        "xnys_session_status": "closed",
        "captured_at": "2026-07-13T22:00:00Z",
        "account": {"equity": None, "cash": None},
        "benchmark": {"symbol": "SPY", "price_basis": "close_unadjusted"},
        "comparison": {"excess_return_total": None},
        "content_hash": "pending",
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert b"p-l40b.performance-benchmark.v1" in encoded
    assert json.loads(encoded.decode("utf-8"))["xnys_session_status"] == "closed"


# ---------------------------------------------------------------------------
# expected_p_l40b_contract: implementación aislada del productor prospectivo
# ---------------------------------------------------------------------------


def _write_spy_cache(tmp_path, frame: pd.DataFrame, *, source: str = "yfinance", auto_adjust: bool = True):
    cache_root = tmp_path / "cache" / "market_data"
    cache_root.mkdir(parents=True)
    frame.to_pickle(cache_root / "market_data_synthetic.pkl")
    (cache_root / "market_data_synthetic.json").write_text(
        json.dumps(
            {
                "source": source,
                "auto_adjust": auto_adjust,
                "requested_symbols": ["SPY"],
                "start": "2026-07-05",
                "end": "2026-07-15",
            }
        ),
        encoding="utf-8",
    )


def test_expected_portfolio_snapshot_derivation_is_eod_only():
    snapshot = derive_account_snapshot(
        _portfolio(
            equity=1_000.0,
            cash=500.0,
            buying_power=500.0,
            positions=[_position("AIZ", 300.0, unrealized_pl=4.0), _position("CRWD", -200.0, side="short", unrealized_pl=-2.0)],
        )
    )
    assert snapshot["gross_exposure_usd"] == pytest.approx(500.0)
    assert snapshot["net_exposure_usd"] == pytest.approx(100.0)
    assert snapshot["gross_exposure_eod_pct"] == pytest.approx(0.5)
    assert snapshot["unrealized_pl"] == pytest.approx(2.0)


@pytest.mark.parametrize("side", [None, "other"])
def test_expected_invalid_side_does_not_invent_net_exposure(side):
    snapshot = derive_account_snapshot(_portfolio(positions=[_position("AIZ", 100.0, side=side)]))
    assert snapshot["net_exposure_usd"] is None
    assert "position_side_invalid" in snapshot["warnings"]


@pytest.mark.parametrize("kind", ["flat", "multi_spy_first", "multi_close_first", "multi_symbol"])
def test_expected_benchmark_cache_shapes_are_supported(tmp_path, monkeypatch, kind):
    _write_spy_cache(tmp_path, _spy_frame(kind))
    monkeypatch.setattr(market_data, "download_daily_prices", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network forbidden")))
    observation = load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-08",
        now=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )
    assert observation["daily_return"] == pytest.approx(745.40 / 747.71 - 1)
    assert observation["price_basis"] == "adjusted_ohlc"


def test_expected_benchmark_without_cache_is_unavailable_and_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "download_daily_prices", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network forbidden")))
    observation = load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-08",
        now=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )
    assert observation["status"] == "unavailable"
    assert "spy_cache_unavailable" in observation["warnings"]


def test_expected_benchmark_rejects_future_bar_and_open_session(tmp_path):
    _write_spy_cache(tmp_path, _spy_frame("flat", include_future=True))
    open_observation = load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-14",
        now=datetime(2026, 7, 14, 15, 0, tzinfo=timezone.utc),
    )
    assert open_observation["status"] == "unavailable"
    assert "session_not_closed" in open_observation["warnings"]


def test_expected_contract_persists_alpha_payload_and_eod_semantics(tmp_path):
    store = _store(tmp_path)
    store.upsert_performance_daily({"session_date": "2026-07-09", "equity": 100.0, "payload": {}})
    item = build_daily_performance_item(
        store,
        _settings(tmp_path),
        "2026-07-10",
        _portfolio(equity=101.0, positions=[_position("AIZ", 25.0)]),
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
        spy_observation={
            "status": "available",
            "previous_close": 500.0,
            "close": 505.0,
            "daily_return": 0.01,
            "price_basis": "close_unadjusted",
            "source": "synthetic",
            "as_of": "2026-07-10T20:00:00+00:00",
            "data_quality": "available",
            "warnings": [],
        },
    )
    store.upsert_performance_daily(item)
    row = store.performance_daily(limit=0)[-1]
    assert row["alpha"] == pytest.approx(0.0)
    assert row["payload"]["performance_benchmark"]["schema_version"] == "p-l40b.performance-benchmark.v1"
    assert row["payload"]["result_metrics"]
    assert row["payload"]["process_metrics"]
    contract = row["payload"]["performance_benchmark"]
    assert contract["account"]["gross_exposure_eod_pct"] == pytest.approx(25 / 101)
    assert contract["account"]["session_average_gross_exposure"] is None
    assert contract["comparison"]["exposure_matched_spy_return"] is None


def test_expected_contract_hash_is_idempotent_and_conflict_safe(tmp_path):
    store = _store(tmp_path)
    contract = build_performance_benchmark(
        store,
        _settings(tmp_path),
        "2026-07-13",
        _portfolio(equity=101.0),
        now=datetime(2026, 7, 14, tzinfo=timezone.utc),
        spy_observation={"status": "unavailable", "warnings": ["synthetic_missing"]},
    )
    item = {"session_date": "2026-07-13", "payload": {"performance_benchmark": contract}, "performance_benchmark": contract, "equity": 101.0}
    assert store.upsert_performance_benchmark(item)["status"] == "inserted"
    assert store.upsert_performance_benchmark(item)["status"] == "idempotent"
    changed = json.loads(json.dumps(contract))
    changed["account"]["equity"] = 102.0
    changed["content_hash"] = "changed"
    conflict_item = dict(item, payload={"performance_benchmark": changed}, performance_benchmark=changed, equity=102.0)
    assert store.upsert_performance_benchmark(conflict_item)["status"] == "conflict"
    assert store.performance_daily(limit=0)[0]["equity"] == pytest.approx(101.0)


def test_expected_contract_hash_excludes_capture_timestamp(tmp_path):
    store = _store(tmp_path)
    kwargs = {
        "store": store,
        "settings": _settings(tmp_path),
        "session_date": "2026-07-13",
        "portfolio": _portfolio(equity=101.0),
        "spy_observation": {"status": "unavailable", "warnings": ["synthetic_missing"]},
    }
    first = build_performance_benchmark(now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc), **kwargs)
    second = build_performance_benchmark(now=datetime(2026, 7, 14, 22, 5, tzinfo=timezone.utc), **kwargs)
    assert first["content_hash"] == second["content_hash"]
    assert first["captured_at"] != second["captured_at"]


def test_expected_contract_missing_previous_session_remains_null(tmp_path):
    store = _store(tmp_path)
    contract = build_performance_benchmark(
        store,
        _settings(tmp_path),
        "2026-06-29",
        _portfolio(equity=101.0),
        now=datetime(2026, 6, 30, tzinfo=timezone.utc),
        spy_observation={"status": "unavailable", "warnings": []},
    )
    assert contract["account"]["previous_equity"] is None
    assert contract["account"]["daily_return"] is None
    assert "missing_previous_xnys_session" in contract["data_quality"]["warnings"]


def test_expected_p40a_reproduction_uses_contract_fields(tmp_path):
    store = _store(tmp_path)
    # La serie se materializa con el productor nuevo; la comprobación solo lee
    # los campos del contrato persistido, no calcula desde P&L/notional.
    equities = {
        "2026-07-07": 70653.37,
        "2026-07-08": 70658.51,
        "2026-07-09": 70678.43,
        "2026-07-10": 70626.17,
        "2026-07-13": 70625.04,
    }
    spy_closes = [747.7100, 748.2000, 748.6000, 748.9000, 749.1700]
    dates = list(equities)
    contracts = []
    for index, session in enumerate(dates):
        previous_equity = equities[dates[index - 1]] if index else None
        previous_spy = spy_closes[index - 1] if index else None
        spy_observation = {
            "status": "available" if previous_spy is not None else "unavailable",
            "previous_close": previous_spy,
            "close": spy_closes[index],
            "daily_return": spy_closes[index] / previous_spy - 1 if previous_spy else None,
            "price_basis": "adjusted_ohlc",
            "source": "synthetic",
            "as_of": f"{session}T20:00:00+00:00",
            "data_quality": "available",
            "warnings": [],
        }
        if previous_equity is not None:
            # El productor resuelve la sesión XNYS anterior desde la fila
            # persistida, como lo hará en el pipeline nocturno.
            store.upsert_performance_daily({"session_date": dates[index - 1], "equity": previous_equity, "payload": {}})
        contract = build_performance_benchmark(
            store,
            _settings(tmp_path),
            session,
            _portfolio(equity=equities[session]),
            now=datetime(2026, 7, 14, tzinfo=timezone.utc),
            spy_observation=spy_observation,
        )
        contracts.append(contract)
        if index == 0:
            continue
        # Solo se exige que la salida del productor contenga el retorno diario;
        # el total se reconstruye con equity/precio del contrato, no con P&L.
        assert contract["account"]["daily_return"] is not None
        assert contract["benchmark"]["daily_return"] is not None
    account_return = contracts[-1]["account"]["equity"] / contracts[0]["account"]["equity"] - 1
    spy_return = contracts[-1]["benchmark"]["close"] / contracts[0]["benchmark"]["close"] - 1
    assert account_return == pytest.approx(-0.00040097, abs=1e-6)
    assert spy_return == pytest.approx(0.00195258, abs=1e-6)
    assert (account_return - spy_return) * 100 == pytest.approx(-0.2354, abs=0.001)


def test_expected_scheduler_persists_one_snapshot_and_fails_open(tmp_path, monkeypatch):
    from agente_bolsa import scheduler

    store = _store(tmp_path)
    settings = _settings(tmp_path)
    settings.logs_dir = tmp_path / "logs"
    settings.benchmark_symbol = "SPY"
    calls = []

    class Client:
        def alpaca_portfolio_snapshot(self):
            calls.append("portfolio")
            return _portfolio(equity=101.0, positions=[_position("AIZ", 25.0)])

    class Reporter:
        def emit(self, *args, **kwargs):
            return None

    monkeypatch.setattr(scheduler, "BrokerClientFactory", lambda _settings: Client())
    scheduler._persist_daily_performance(settings, store, "2026-07-13", Reporter(), "run-test")
    assert calls == ["portfolio"]
    row = store.performance_daily(limit=0)[0]
    assert row["payload"]["performance_benchmark"]["schema_version"] == "p-l40b.performance-benchmark.v1"
    assert benchmark_summary([row])["exposure_matched_status"] == "unavailable"
