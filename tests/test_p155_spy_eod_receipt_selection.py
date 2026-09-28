"""P-L155 caracterizacion: el lector de recibos EOD de SPY elige por reloj.

Reproduce la sesion 2026-09-24 tal y como quedo en produccion: cuatro recibos
validos con sufijos de nombre de fichero que ordenan alfabeticamente distinto
del orden temporal. El sufijo es ``content_hash[:8]``, no tiempo, asi que ordenar
por nombre devuelve un ``unavailable`` y tapa los dos ``comparable``.

Todo el contenido de los recibos se genera con el productor real
``build_spy_eod_receipt``; solo el nombre del fichero replica el de produccion.
Sin red, sin broker, sin LLM, sin SQLite productiva y con `DATA_DIR` temporal.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools import market_data, performance_benchmark
from agente_bolsa.tools.spy_eod_authority import (
    build_spy_eod_receipt,
    load_spy_eod_receipt,
    refresh_and_capture_spy_eod,
    spy_eod_coverage,
)

SESSION = "2026-09-24"
PREVIOUS = "2026-09-23"
PREV_CLOSE = 681.42
CLOSE = 686.11

# Sufijos reales de /var/lib/agente-bolsa/cache/market_data para 2026-09-24.
# Orden alfabetico: 37277f9b < 8a09005c < a5284111 < fdf426ce. `reversed` empieza
# por fdf426ce (unavailable) y por eso tapa los dos comparables.
PROD_NAMES = ("37277f9b", "8a09005c", "a5284111", "fdf426ce")


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=Path(tmp_path),
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
    )


def _write_price_cache(settings, *, created_at, name):
    cache_root = Path(settings.data_dir) / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Adj Close": [PREV_CLOSE, CLOSE]},
        index=pd.DatetimeIndex([pd.Timestamp(PREVIOUS), pd.Timestamp(SESSION)]),
    )
    frame.to_pickle(cache_root / f"market_data_{name}.pkl")
    meta = {
        "requested_symbols": ["SPY"],
        "source": "yfinance",
        "interval": "1d",
        "start": PREVIOUS,
        "end": SESSION,
        "created_at": created_at,
        "price_basis": "adjusted_ohlc",
    }
    (cache_root / f"market_data_{name}.json").write_text(json.dumps(meta), encoding="utf-8")
    return cache_root / f"market_data_{name}.pkl"


def _write_receipt_file(settings, receipt, suffix):
    """Escribe el recibo tal cual lo deja el productor, con el nombre de produccion."""
    root = Path(settings.data_dir) / "cache" / "market_data"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"spy_eod_close_{SESSION.replace('-', '')}_{suffix}.json"
    path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _production_session_20260924(settings):
    """Cuatro recibos de la sesion 2026-09-24 con la distribucion de produccion.

    Dos comparables (8a09005c, a5284111) y dos unavailable (37277f9b,
    fdf426ce). El unavailable fdf426ce tiene el `captured_at` mas reciente, que
    es el caso mas duro: el orden alfabetico invertido tambien lo elige primero.
    """
    # comparable EOD valido.
    _write_price_cache(settings, created_at="2026-09-25T01:00:00+00:00", name="eod")
    comparable_early = build_spy_eod_receipt(
        settings, SESSION, now=datetime(2026, 9, 25, 8, 40, 11, tzinfo=timezone.utc)
    )
    assert comparable_early["comparison_status"] == "comparable"
    _write_receipt_file(settings, comparable_early, "8a09005c")
    comparable_late = build_spy_eod_receipt(
        settings, SESSION, now=datetime(2026, 9, 25, 22, 5, 47, tzinfo=timezone.utc)
    )
    assert comparable_late["comparison_status"] == "comparable"
    _write_receipt_file(settings, comparable_late, "a5284111")

    # El recibo comparable mas reciente es el que debe ganar.
    (Path(settings.data_dir) / "cache" / "market_data" / "market_data_eod.pkl").unlink()
    (Path(settings.data_dir) / "cache" / "market_data" / "market_data_eod.json").unlink()

    # Cache same-day: P-L71 sigue cerrada, produce unavailable.
    _write_price_cache(settings, created_at="2026-09-24T21:00:00+00:00", name="same_day")
    unavailable_early = build_spy_eod_receipt(
        settings, SESSION, now=datetime(2026, 9, 26, 0, 12, 4, tzinfo=timezone.utc)
    )
    assert unavailable_early["comparison_status"] == "unavailable"
    _write_receipt_file(settings, unavailable_early, "37277f9b")
    unavailable_late = build_spy_eod_receipt(
        settings, SESSION, now=datetime(2026, 9, 26, 21, 33, 2, tzinfo=timezone.utc)
    )
    assert unavailable_late["comparison_status"] == "unavailable"
    _write_receipt_file(settings, unavailable_late, "fdf426ce")
    return comparable_early, comparable_late, unavailable_early, unavailable_late


# --- A1: la sesion 2026-09-24 de produccion entrega un comparable -----------


def test_a1_unavailable_no_tapa_comparable_de_la_misma_sesion(tmp_path):
    settings = _settings(tmp_path)
    _production_session_20260924(settings)

    receipt = load_spy_eod_receipt(settings, SESSION)

    assert receipt is not None
    assert receipt["comparison_status"] == "comparable", receipt.get("reason_codes")
    assert receipt["daily_return"] is not None
    assert receipt["reason_codes"] == []


def test_a1_gana_el_comparable_mas_reciente_por_captured_at(tmp_path):
    settings = _settings(tmp_path)
    comparable_early, comparable_late, _unused_a, _unused_b = _production_session_20260924(settings)

    receipt = load_spy_eod_receipt(settings, SESSION)

    assert receipt["content_hash"] == comparable_late["content_hash"]
    assert receipt["content_hash"] != comparable_early["content_hash"]


# --- A2: dos comparables y comparable vs unavailable -----------------------


def _write_named_receipt(settings, suffix, *, now, comparable, cache_created_at):
    if comparable:
        _write_price_cache(settings, created_at=cache_created_at, name="eod")
    else:
        _write_price_cache(settings, created_at="2026-09-24T21:00:00+00:00", name="same_day")
    receipt = build_spy_eod_receipt(settings, SESSION, now=now)
    assert receipt["comparison_status"] == ("comparable" if comparable else "unavailable")
    return _write_receipt_file(settings, receipt, suffix)


def test_a2_dos_comparables_gana_el_captured_at_mas_reciente(tmp_path):
    settings = _settings(tmp_path)
    # El nombre ordena al viejo por delante del nuevo: el hash del nombre no
    # puede decidir. Gana el `captured_at` mas reciente.
    _write_named_receipt(
        settings,
        "ffff0001",
        now=datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
        comparable=True,
        cache_created_at="2026-09-25T01:00:00+00:00",
    )
    _write_named_receipt(
        settings,
        "0000ffff",
        now=datetime(2026, 9, 25, 22, 0, tzinfo=timezone.utc),
        comparable=True,
        cache_created_at="2026-09-25T02:00:00+00:00",
    )

    receipt = load_spy_eod_receipt(settings, SESSION)

    assert receipt["captured_at"] == "2026-09-25T22:00:00+00:00"
    assert receipt["comparison_status"] == "comparable"


def test_a2_unavailable_posterior_no_tapa_al_comparable(tmp_path):
    settings = _settings(tmp_path)
    _write_named_receipt(
        settings,
        "ffff0001",
        now=datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
        comparable=True,
        cache_created_at="2026-09-25T01:00:00+00:00",
    )
    _write_named_receipt(
        settings,
        "0000ffff",
        now=datetime(2026, 9, 26, 21, 33, tzinfo=timezone.utc),
        comparable=False,
        cache_created_at="2026-09-24T21:00:00+00:00",
    )

    receipt = load_spy_eod_receipt(settings, SESSION)

    assert receipt["comparison_status"] == "comparable"
    assert receipt["captured_at"] == "2026-09-25T08:00:00+00:00"


def test_a2_empate_de_reloj_es_estable_y_repetible(tmp_path):
    settings = _settings(tmp_path)
    stamp = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
    _write_named_receipt(
        settings, "ffff0001", now=stamp, comparable=True, cache_created_at="2026-09-25T01:00:00+00:00"
    )
    _write_named_receipt(
        settings, "0000ffff", now=stamp, comparable=True, cache_created_at="2026-09-25T02:00:00+00:00"
    )

    first = load_spy_eod_receipt(settings, SESSION)
    second = load_spy_eod_receipt(settings, SESSION)

    assert first["receipt_path"] == second["receipt_path"]
    assert first["content_hash"] == second["content_hash"]


def test_recibo_invalido_se_ignora_como_hoy(tmp_path):
    settings = _settings(tmp_path)
    root = Path(settings.data_dir) / "cache" / "market_data"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"spy_eod_close_{SESSION.replace('-', '')}_ffff0001.json").write_text(
        json.dumps({"schema_version": "otro", "session_date": SESSION}), encoding="utf-8"
    )
    tampered = build_spy_eod_receipt(
        settings, SESSION, now=datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    )
    _write_receipt_file(settings, tampered, "0000ffff")
    payload = json.loads((root / f"spy_eod_close_{SESSION.replace('-', '')}_0000ffff.json").read_text(encoding="utf-8"))
    payload["close"] = 1.0
    (root / f"spy_eod_close_{SESSION.replace('-', '')}_0000ffff.json").write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )

    assert load_spy_eod_receipt(settings, SESSION) is None


def test_ficheros_existentes_no_se_reescriben_ni_se_borran(tmp_path):
    settings = _settings(tmp_path)
    path = _write_named_receipt(
        settings,
        "ffff0001",
        now=datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
        comparable=True,
        cache_created_at="2026-09-25T01:00:00+00:00",
    )
    before = (path.read_text(encoding="utf-8"), path.stat().st_mtime_ns)

    load_spy_eod_receipt(settings, SESSION)
    spy_eod_coverage(settings, PREVIOUS, SESSION)

    assert (path.read_text(encoding="utf-8"), path.stat().st_mtime_ns) == before


# --- A3: la cache same-day sigue unavailable (P-L71 no se relaja) -----------


def test_a3_cache_same_day_sigue_unavailable(tmp_path):
    settings = _settings(tmp_path)
    _write_price_cache(settings, created_at="2026-09-24T21:00:00+00:00", name="same_day")

    receipt = build_spy_eod_receipt(
        settings, SESSION, now=datetime(2026, 9, 25, 22, 0, tzinfo=timezone.utc)
    )

    assert receipt["comparison_status"] == "unavailable"
    assert "same_day_cache_not_eod" in receipt["reason_codes"]
    assert receipt["daily_return"] is None


def test_a3_overlay_sin_comparable_no_inventa_benchmark(tmp_path):
    settings = _settings(tmp_path)
    _write_price_cache(settings, created_at="2026-09-24T21:00:00+00:00", name="same_day")
    receipt = build_spy_eod_receipt(
        settings, SESSION, now=datetime(2026, 9, 25, 22, 0, tzinfo=timezone.utc)
    )
    _write_receipt_file(settings, receipt, "ffff0001")

    projected = performance_benchmark.overlay_eod_benchmark(
        _performance_row(), settings, now=datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    )
    benchmark = projected["payload"]["performance_benchmark"]["benchmark"]

    assert benchmark["daily_return"] is None
    assert benchmark["comparison_status"] == "unavailable"
    assert projected["eod_overlay_status"] == "unavailable"


# --- A4: el reloj del productor se toma despues de la descarga --------------


def test_a4_reloj_posterior_a_la_descarga_no_produce_cache_created_at_future(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    entry = datetime(2026, 9, 25, 21, 30, tzinfo=timezone.utc)
    download_clock = entry + timedelta(seconds=5)
    calls: list[tuple] = []

    def fake_download(symbols, start, end, *, cache_dir, provider, **kwargs):
        calls.append((tuple(symbols), start, end))
        holder = _settings(tmp_path)
        _write_price_cache(holder, created_at=download_clock.isoformat(), name="downloaded")
        return pd.DataFrame(), {
            "created_at": download_clock.isoformat(),
            "source": "yfinance",
            "requested_symbols": ["SPY"],
            "interval": "1d",
            "start": start,
            "end": end,
            "price_basis": "adjusted_ohlc",
        }

    monkeypatch.setattr(market_data, "download_daily_prices_with_metadata", fake_download)

    result = refresh_and_capture_spy_eod(settings, SESSION, now=entry)

    assert calls, "no debe saltarse la descarga con la sesion cerrada"
    receipt = result["receipt"]
    assert result["persisted"] is True
    assert receipt["comparison_status"] == "comparable", receipt["reason_codes"]
    assert "cache_created_at_future" not in receipt["reason_codes"]
    assert receipt["captured_at"] >= download_clock.isoformat()
    assert receipt["cache_created_at"] == download_clock.isoformat()


def test_a4_sesion_no_cerrada_no_descarga(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    calls: list[tuple] = []

    def exploding_download(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("no debe descargar con la sesion abierta")

    monkeypatch.setattr(market_data, "download_daily_prices_with_metadata", exploding_download)

    result = refresh_and_capture_spy_eod(
        settings, SESSION, now=datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)
    )

    assert calls == []
    assert result["persisted"] is False
    assert result["reason"] == "session_not_closed"
    assert result["receipt"] is None


def test_a4_descarga_caida_sigue_fail_open(tmp_path, monkeypatch):
    settings = _settings(tmp_path)

    def failing_download(*args, **kwargs):
        raise RuntimeError("sin red")

    monkeypatch.setattr(market_data, "download_daily_prices_with_metadata", failing_download)

    result = refresh_and_capture_spy_eod(
        settings, SESSION, now=datetime(2026, 9, 25, 21, 30, tzinfo=timezone.utc)
    )

    assert result["persisted"] is False
    assert result["reason"] == "fetch_failed_open:RuntimeError"
    assert result["receipt"] is None
    assert not list((Path(tmp_path) / "cache" / "market_data").glob("spy_eod_close_*.json"))


# --- A5: efecto que ve el operador en el overlay --------------------------


def _performance_row() -> dict:
    return {
        "session_date": SESSION,
        "payload": {
            "performance_benchmark": {
                "schema_version": "p-l40b.performance-benchmark.v1",
                "captured_at": "2026-09-24T20:27:17+00:00",
                "account": {
                    "equity": 70634.91,
                    "previous_equity": 70534.69,
                    "daily_return": 0.00142086,
                },
                "benchmark": {
                    "symbol": "SPY",
                    "instrument_label": "SPY (ETF S&P 500)",
                    "previous_close": 681.42,
                    "close": 686.11,
                    "daily_return": 0.00688,
                    "price_basis": "adjusted_ohlc",
                    "source": "yfinance",
                    "as_of": "2026-09-24T00:00:00",
                    "data_quality": "partial",
                },
                "comparison": {"excess_return_total": 0.00446514},
                "data_quality": {"status": "partial", "warnings": []},
                "content_hash": "stored-original-hash",
            }
        },
    }


def test_a5_overlay_entrega_comparable_con_los_cuatro_recibos(tmp_path):
    settings = _settings(tmp_path)
    _production_session_20260924(settings)

    projected = performance_benchmark.overlay_eod_benchmark(
        _performance_row(), settings, now=datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    )
    contract = projected["payload"]["performance_benchmark"]
    benchmark = contract["benchmark"]

    assert benchmark["daily_return"] is not None
    assert benchmark["daily_return"] == pytest.approx(CLOSE / PREV_CLOSE - 1.0)
    assert benchmark["comparison_status"] == "comparable"
    assert benchmark["data_quality"] == "available"
    assert contract["comparison"]["excess_return_total"] is not None
    assert contract["content_hash"] == "stored-original-hash"


# --- A9: cobertura observable ----------------------------------------------


def test_a9_cobertura_cuenta_la_sesion_tapada(tmp_path):
    settings = _settings(tmp_path)
    _production_session_20260924(settings)

    coverage = spy_eod_coverage(settings, PREVIOUS, SESSION)

    assert coverage["denominator"] == "xnys_sessions"
    assert coverage["sessions_total"] == 2
    assert coverage["sessions_comparable"] == 1
    assert coverage["sessions_unavailable"] == 1
    assert coverage["provisional"] is True
    row = {item["session_date"]: item for item in coverage["by_session"]}[SESSION]
    assert row["comparison_status"] == "comparable"
    assert row["reason_codes"] == []


def test_a9_autoridad_cache_sigue_fallando_cerrada_sin_recibo(tmp_path):
    settings = _settings(tmp_path)
    _write_price_cache(settings, created_at="2026-09-24T21:00:00+00:00", name="same_day")

    observed = performance_benchmark.load_cached_spy_observation(
        settings, SESSION, now=datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    )

    assert observed["status"] == "unavailable"
    assert "same_day_cache_not_eod" in observed["warnings"]
    assert load_spy_eod_receipt(settings, SESSION) is None
