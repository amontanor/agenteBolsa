"""Persistent signal learning and outcome attribution."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.storage import Store

from ..agent_registry import canonical_agent_id
from ..agent_run import AGENT_PRODUCER_SCHEMA_VERSION, EXECUTION_KINDS
from ..market_calendar import MarketCalendar
from .h_capture import (
    PREDICTION_EVENT_TYPE,
    build_outcome_capture,
    build_prediction_capture,
    persist_h_capture_event,
    validate_h_capture_event,
)
from .learning_mode import LOW_SAMPLE_EXPLORATION_TAG
from .market_data import download_daily_prices
from .signal_identity import build_signal_capture, canonical_signal_id, signal_identity_block

HORIZONS = (1, 3, 5, 10)
AGENT_LEARNING_SCHEMA_VERSION = "p-l104.agent-learning.v1"
AGENT_LEARNING_SIGNAL_LIMIT = 160
AGENT_LEARNING_FEEDBACK_SCHEMA_VERSION = "p-l104.agent-learning-feedback.v1"
AGENT_EVIDENCE_PACKET_SCHEMA_VERSION = "p-l104.agent-evidence-packet.v1"
AGENT_CONTRACT_SCHEMA_VERSION = "p-l84b.agent-contract.v1"
AGENT_VALIDATION_ARTIFACT_SCHEMA_VERSION = "p-l118.agent-learning-validation.v1"
CanonicalValidationResolver = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]
LEARNING_NET_10BPS_COST = 0.001
LEARNING_NET_20BPS_COST = 0.002
LEARNING_GROSS_HIT_THRESHOLD = 0.01
LOGGER = logging.getLogger(__name__)


def _portfolio_metrics_unavailable() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": "portfolio_replay_required",
        "sample_unit": "portfolio",
        "required_inputs": ["fills", "marks", "cash_flows", "costs"],
    }


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date(value: Any) -> str:
    text = str(value or "")
    if "T" in text:
        return text[:10]
    return text[:10] if text else datetime.now(timezone.utc).date().isoformat()


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.upper()).strip("_")


def _chart_pattern_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    technical_state = candidate.get("technical_state", {}) or {}
    patterns = technical_state.get("chart_patterns", []) or candidate.get("chart_patterns", []) or []
    confirmed = [item for item in patterns if item.get("status") == "confirmed"]
    bullish = [item for item in confirmed if item.get("bias") == "bullish"]
    bearish = [item for item in confirmed if item.get("bias") == "bearish"]
    return {
        "confirmed_count": len(confirmed),
        "bullish_confirmed_count": len(bullish),
        "bearish_confirmed_count": len(bearish),
        "labels": [str(item.get("label") or item.get("pattern")) for item in confirmed[:5]],
    }


def _signal_features(candidate: dict[str, Any]) -> dict[str, Any]:
    technical_state = candidate.get("technical_state", {}) or {}
    risk = candidate.get("risk_plan", {}) or {}
    close = _num(technical_state.get("close"))
    sma20 = _num(technical_state.get("sma_20"))
    sma200 = _num(technical_state.get("sma_200"))
    macd = _num(technical_state.get("macd"))
    macd_signal = _num(technical_state.get("macd_signal"))
    return {
        "direction": candidate.get("direction"),
        "score": candidate.get("score"),
        "setup_name": candidate.get("setup_name"),
        "selection_score": _num(candidate.get("selection_score")),
        "selection_rank": candidate.get("selection_rank"),
        "selection_reason": candidate.get("selection_reason"),
        "strategy_name": candidate.get("strategy_name"),
        "strategy_version": candidate.get("strategy_version"),
        "strategy_status": candidate.get("strategy_status"),
        "shadow_candidate": bool(candidate.get("shadow_candidate")),
        "cohort": candidate.get("cohort"),
        "learning_mode": bool(candidate.get("learning_mode")),
        "negative_pocket_shadow_penalties": candidate.get("negative_pocket_shadow_penalties", {}),
        "negative_pocket_penalty_applied": bool(candidate.get("negative_pocket_penalty_applied")),
        "blocked_auto_buy": bool(candidate.get("blocked_auto_buy")),
        "blocked_auto_buy_reason": candidate.get("blocked_auto_buy_reason"),
        "setup_quality": candidate.get("setup_quality"),
        "market_regime": candidate.get("market_regime") or technical_state.get("market_regime"),
        "volatility_regime": candidate.get("volatility_regime") or technical_state.get("volatility_regime"),
        "risk_posture": candidate.get("risk_posture") or technical_state.get("risk_posture"),
        "market_state_quality": candidate.get("market_state_quality") or technical_state.get("market_state_quality"),
        "last_date": _date(candidate.get("last_date")),
        "close": close,
        "entry_price": _num(risk.get("entry_price"), close),
        "stop_loss": _num(risk.get("stop_loss")),
        "take_profit": _num(risk.get("take_profit")),
        "return_5d": _num(technical_state.get("return_5d")),
        "return_20d": _num(technical_state.get("return_20d")),
        "return_60d": _num(technical_state.get("return_60d")),
        "rsi_14": _num(technical_state.get("rsi_14")),
        "macd_diff": (macd - macd_signal) if macd is not None and macd_signal is not None else None,
        "volume_zscore_20": _num(technical_state.get("volume_zscore_20")),
        "bollinger_pct_b_20": _num(technical_state.get("bollinger_pct_b_20")),
        "gap_pct": _num(technical_state.get("gap_pct")),
        "close_position_in_range": _num(technical_state.get("close_position_in_range")),
        "breakout_continuation_long": bool(technical_state.get("breakout_continuation_long")),
        "range_expansion_breakout_long": bool(technical_state.get("range_expansion_breakout_long")),
        "orderly_breakout_long": bool(technical_state.get("orderly_breakout_long")),
        "breakout_failure_risk": bool(technical_state.get("breakout_failure_risk")),
        "event_momentum_long": bool(technical_state.get("event_momentum_long")),
        "momentum_shakeout_hold_long": bool(technical_state.get("momentum_shakeout_hold_long")),
        "distance_sma20": ((close - sma20) / sma20) if close and sma20 else None,
        "distance_sma200": ((close - sma200) / sma200) if close and sma200 else None,
        "chart_patterns": _chart_pattern_summary(candidate),
        "reasons": candidate.get("reasons", [])[:8],
        "producer_agent_contract": candidate.get("producer_agent_contract"),
    }


def _market_regime_features(report: dict[str, Any]) -> dict[str, Any]:
    state = report.get("market_state") if isinstance(report.get("market_state"), dict) else {}
    return {
        "market_regime": (
            state.get("market_regime")
            or report.get("market_regime")
            or report.get("regime")
            or ((report.get("summary") or {}).get("market_regime") if isinstance(report.get("summary"), dict) else None)
        ),
        "volatility_regime": state.get("volatility_regime") or report.get("volatility_regime"),
        "risk_posture": state.get("risk_posture") or report.get("risk_posture"),
        "market_state_quality": ((state.get("data_quality") or {}).get("status") if isinstance(state.get("data_quality"), dict) else None)
        or report.get("market_state_quality"),
    }


def _apply_signal_candidate_identities(
    report: dict[str, Any],
    *,
    source: str,
    identity_by_key: dict[str, dict[str, Any]],
    ambiguous_keys: set[str],
) -> None:
    """Carry producer-owned identity into each in-memory candidate copy."""

    for bucket_name in ("all_candidates", "selected_candidates", "top_longs", "top_shorts"):
        for candidate in list(report.get(bucket_name, []) or []):
            if not isinstance(candidate, dict):
                continue
            key = canonical_signal_id(source, candidate)
            identity = identity_by_key.get(key)
            if identity and key not in ambiguous_keys:
                candidate.update(
                    {
                        field: value
                        for field, value in identity.items()
                        if field != "signal_capture"
                    }
                )
                candidate["signal_identity_status"] = "verified"
            elif key in ambiguous_keys:
                for field in (
                    "signal_id",
                    "signal_capture_id",
                    "signal_source_run_id",
                    "signal_date",
                    "signal_strategy_name",
                    "signal_strategy_version",
                ):
                    candidate.pop(field, None)
                candidate["signal_identity_status"] = "ambiguous"


def prepare_signal_candidate_identities(
    report: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """Mint signal identity once, before learning annotation and ranking.

    This is the producer boundary. Consumers receive the concrete IDs copied
    here and never reconstruct them from a symbol/date after ranking.
    """

    source_run_id = str(report.get("run_id") or "")
    if not source_run_id:
        return {
            "source": source,
            "source_run_id": None,
            "identity_by_key": {},
            "ambiguous_keys": set(),
        }
    active_candidates = list(report.get("all_candidates", []) or [])
    identity_by_key: dict[str, dict[str, Any]] = {}
    ambiguous_keys: set[str] = set()
    for candidate in active_candidates:
        if isinstance(candidate, dict):
            key = canonical_signal_id(source, candidate)
            if key in identity_by_key:
                ambiguous_keys.add(key)
                continue
            signal_id = str(candidate.get("signal_id") or key)
            signal_source_run_id = candidate.get("signal_source_run_id") or source_run_id
            raw_signal_date = (
                candidate.get("signal_date")
                or candidate.get("last_date")
                or (candidate.get("technical_state") or {}).get("last_date")
            )
            signal_date = _date(raw_signal_date) if raw_signal_date else ""
            capture = build_signal_capture(
                {
                    **candidate,
                    "signal_id": signal_id,
                    "signal_source_run_id": signal_source_run_id,
                    "signal_date": signal_date,
                },
                source_run_id=signal_source_run_id,
                captured_at=report.get("as_of"),
            )
            identity = {
                "signal_id": signal_id,
                "signal_source_run_id": signal_source_run_id,
                "signal_capture_id": capture.get("signal_capture_id") if capture else None,
                "signal_date": signal_date,
                "candidate_id": candidate.get("candidate_id"),
                "signal_strategy_name": candidate.get("signal_strategy_name") or candidate.get("strategy_name"),
                "signal_strategy_version": candidate.get("signal_strategy_version") or candidate.get("strategy_version"),
                "signal_capture": capture,
            }
            identity_by_key[key] = identity
    _apply_signal_candidate_identities(
        report,
        source=source,
        identity_by_key=identity_by_key,
        ambiguous_keys=ambiguous_keys,
    )
    return {
        "source": source,
        "source_run_id": source_run_id,
        "identity_by_key": identity_by_key,
        "ambiguous_keys": ambiguous_keys,
    }


def _normalize_producer_agent_contract(
    value: Any,
    *,
    expected_cycle_id: str | None = None,
) -> dict[str, Any] | None:
    """Accept only a complete producer identity from the producer boundary."""

    if not isinstance(value, dict):
        return None
    raw_role = str(value.get("raw_role") or "").strip()
    canonical = str(value.get("canonical_agent_id") or "").strip()
    execution_kind = str(value.get("execution_kind") or "").strip()
    required = {
        "schema_version": value.get("schema_version"),
        "raw_role": raw_role,
        "canonical_agent_id": canonical,
        "agent_run_id": str(value.get("agent_run_id") or "").strip(),
        "cycle_id": str(value.get("cycle_id") or "").strip(),
        "execution_kind": execution_kind,
    }
    if required["schema_version"] != AGENT_PRODUCER_SCHEMA_VERSION:
        return None
    if (
        not raw_role
        or not canonical
        or not required["agent_run_id"]
        or not required["cycle_id"]
        or execution_kind not in EXECUTION_KINDS
    ):
        return None
    if canonical_agent_id(raw_role) != canonical:
        return None
    if expected_cycle_id and required["cycle_id"] != expected_cycle_id:
        return None
    for field in ("provider", "model", "parent_run_id", "retry_of", "fallback_reason"):
        value_text = str(value.get(field) or "").strip()
        required[field] = value_text or None
    return required


def _apply_producer_agent_contract(
    report: dict[str, Any],
    contract: dict[str, Any] | None,
) -> None:
    if contract is None:
        return
    report["producer_agent_contract"] = dict(contract)
    for bucket_name in ("all_candidates", "selected_candidates", "top_longs", "top_shorts", "shadow_candidates"):
        for candidate in list(report.get(bucket_name, []) or []):
            if isinstance(candidate, dict) and "producer_agent_contract" not in candidate:
                candidate["producer_agent_contract"] = dict(contract)


def _explicit_prediction(
    candidate: Mapping[str, Any],
    report: Mapping[str, Any],
    signal_id: str,
) -> dict[str, Any] | None:
    value = candidate.get("prospective_prediction")
    if isinstance(value, Mapping):
        return dict(value)
    by_signal = report.get("prospective_predictions")
    if isinstance(by_signal, Mapping):
        value = by_signal.get(signal_id)
        if isinstance(value, Mapping):
            return dict(value)
    return None


def _persist_signal_prediction_captures(
    store: Store,
    report: Mapping[str, Any],
    capture_requests: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]],
) -> None:
    for row, candidate, producer_contract in capture_requests:
        try:
            contract = producer_contract or {}
            prediction = _explicit_prediction(candidate, report, str(row.get("signal_id") or ""))
            lineage = {
                "cycle_id": contract.get("cycle_id"),
                "agent_run_id": contract.get("agent_run_id"),
                "agent_name": contract.get("canonical_agent_id") or contract.get("raw_role"),
                "signal_id": row.get("signal_id"),
                "signal_capture_id": row.get("features", {}).get("signal_capture_id"),
                "signal_source_run_id": row.get("features", {}).get("signal_source_run_id"),
                "candidate_id": candidate.get("candidate_id"),
                "source_event_id": prediction.get("source_event_id") if prediction else None,
                "source_event_content_hash": (
                    prediction.get("source_event_content_hash") or prediction.get("source_content_hash")
                    if prediction
                    else None
                ),
            }
            payload = build_prediction_capture(
                lineage=lineage,
                prediction=prediction,
                capture_observed_at=report.get("as_of"),
                producer_stage="signal_candidate",
                calendar_name="XNYS",
            )
            persist_h_capture_event(store, payload)
        except Exception as exc:  # noqa: BLE001 - shadow telemetry never blocks trading.
            if isinstance(report, dict):
                report.setdefault("warnings", []).append("prospective_capture_persistence_failed")
            LOGGER.warning("No se pudo construir o persistir captura prospectiva: %s", exc, exc_info=True)


def _iter_signal_prediction_events(
    store: Store,
    signals: list[dict[str, Any]],
):
    """Stream only relevant prediction events without a historical read cap."""

    cycle_ids: set[str] = set()
    requires_unscoped_scan = False
    for signal in signals:
        source_run_id = str(signal.get("source_run_id") or "").strip()
        if source_run_id:
            cycle_ids.add(source_run_id)
        features = signal.get("features", {}) or {}
        contract = features.get("producer_agent_contract")
        if isinstance(contract, Mapping):
            contract_cycle_id = str(contract.get("cycle_id") or "").strip()
            if contract_cycle_id:
                cycle_ids.add(contract_cycle_id)
            else:
                requires_unscoped_scan = True
        else:
            # A missing producer contract can have a null event cycle_id. The
            # fallback remains streaming and exact-filtered; it is not capped.
            requires_unscoped_scan = True

    iterator = getattr(store, "iter_agent_events", None)
    if not callable(iterator):
        raise AttributeError("store_iter_agent_events_required")
    if requires_unscoped_scan or not cycle_ids:
        yield from iterator(
            event_type_prefix=PREDICTION_EVENT_TYPE,
            limit=None,
            batch_size=256,
        )
        return
    for cycle_id in sorted(cycle_ids):
        yield from iterator(
            event_type_prefix=PREDICTION_EVENT_TYPE,
            cycle_id=cycle_id,
            limit=None,
            batch_size=256,
        )


def _prediction_matches_signal(
    prediction_event: Mapping[str, Any],
    row: Mapping[str, Any],
    signal: Mapping[str, Any],
) -> bool:
    """Require the stored capture to identify the exact signal lineage."""

    features = signal.get("features", {}) or {}
    if not isinstance(features, Mapping):
        return False
    for field in ("signal_id", "signal_capture_id", "signal_source_run_id", "candidate_id"):
        expected = signal.get(field) or features.get(field)
        actual = prediction_event.get(field)
        if not str(expected or "").strip() or str(actual or "").strip() != str(expected).strip():
            return False
    producer_contract = features.get("producer_agent_contract")
    if isinstance(producer_contract, Mapping):
        expected_cycle_id = str(producer_contract.get("cycle_id") or "").strip()
        expected_agent_run_id = str(producer_contract.get("agent_run_id") or "").strip()
        if expected_cycle_id and str(row.get("cycle_id") or "").strip() != expected_cycle_id:
            return False
        if (
            expected_agent_run_id
            and str(prediction_event.get("agent_run_id") or "").strip() != expected_agent_run_id
        ):
            return False
    return True


def _persist_signal_outcome_captures(
    settings: Settings,
    store: Store,
    signals: list[dict[str, Any]],
    data: pd.DataFrame,
    *,
    observed_at: datetime,
) -> bool:
    observation_failed = False
    try:
        signals_by_id: dict[str, dict[str, Any]] = {}
        ambiguous_signal_ids: set[str] = set()
        for signal in signals:
            signal_id = str(signal.get("signal_id") or "").strip()
            if not signal_id:
                continue
            identity = (
                str(signal.get("symbol") or "").upper().strip(),
                str(signal.get("source_run_id") or "").strip(),
            )
            previous = signals_by_id.get(signal_id)
            if previous is not None:
                previous_identity = (
                    str(previous.get("symbol") or "").upper().strip(),
                    str(previous.get("source_run_id") or "").strip(),
                )
                if previous_identity != identity:
                    ambiguous_signal_ids.add(signal_id)
                    continue
            signals_by_id[signal_id] = signal

        calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
        frame_by_symbol: dict[str, pd.DataFrame] = {}
        for row in _iter_signal_prediction_events(store, signals):
            if not validate_h_capture_event(row, expected_event_type=PREDICTION_EVENT_TYPE):
                LOGGER.warning("Se descarta evento H invÃ¡lido antes de observar outcome: %s", row.get("event_id"))
                continue
            prediction_event = row.get("payload")
            if not isinstance(prediction_event, dict):
                continue
            signal_id = str(prediction_event.get("signal_id") or "").strip()
            signal = signals_by_id.get(signal_id)
            if not signal or signal_id in ambiguous_signal_ids:
                continue
            if not _prediction_matches_signal(prediction_event, row, signal):
                LOGGER.warning(
                    "Se descarta evento H sin lineage exacto para signal_id=%s",
                    signal_id,
                )
                continue
            try:
                symbol = str(signal.get("symbol") or "")
                if symbol not in frame_by_symbol:
                    frame_by_symbol[symbol] = _symbol_frame(data, symbol)
                payload = build_outcome_capture(
                    prediction_event,
                    price_frame=frame_by_symbol[symbol],
                    observed_at=observed_at,
                    market_calendar=calendar,
                    outcome_source_ref={
                        "kind": "signal_outcomes",
                        "signal_id": signal_id,
                        "source_run_id": signal.get("source_run_id"),
                    },
                )
                persist_h_capture_event(store, payload)
            except Exception:  # noqa: BLE001 - outcome observation cannot block trading.
                observation_failed = True
                LOGGER.exception("No se pudo persistir outcome prospectivo para %s", signal_id)
    except Exception:  # noqa: BLE001 - observation cannot block legacy outcomes.
        observation_failed = True
        LOGGER.exception("No se pudo recorrer capturas prospectivas de seÃ±ales")
    return not observation_failed


def record_signal_candidates(
    store: Store,
    report: dict[str, Any],
    *,
    source: str,
    prepared_identity: dict[str, Any] | None = None,
    producer_agent_contract: dict[str, Any] | None = None,
) -> int:
    source_run_id = str(report.get("run_id") or "")
    if not source_run_id:
        return 0
    raw_producer_contract = (
        producer_agent_contract
        if producer_agent_contract is not None
        else report.get("producer_agent_contract")
    )
    normalized_producer_contract = _normalize_producer_agent_contract(
        raw_producer_contract,
        expected_cycle_id=source_run_id,
    )
    if raw_producer_contract is not None and normalized_producer_contract is None:
        report.setdefault("warnings", []).append("producer_agent_identity_unavailable")
    _apply_producer_agent_contract(report, normalized_producer_contract)
    prepared = prepared_identity or {}
    if (
        prepared.get("source") != source
        or prepared.get("source_run_id") != source_run_id
    ):
        prepared = prepare_signal_candidate_identities(report, source=source)
    identity_by_key = dict(prepared.get("identity_by_key") or {})
    ambiguous_keys = set(prepared.get("ambiguous_keys") or set())
    _apply_signal_candidate_identities(
        report,
        source=source,
        identity_by_key=identity_by_key,
        ambiguous_keys=ambiguous_keys,
    )
    rows = []
    capture_requests: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]] = []
    active_candidates = list(report.get("all_candidates", []) or [])
    shadow_candidates = list(report.get("shadow_candidates", []) or [])
    candidates = [
        {**candidate, "shadow_candidate": False}
        for candidate in active_candidates
    ] + [
        {**candidate, "shadow_candidate": True, "strategy_status": str(candidate.get("strategy_status") or "SHADOW")}
        for candidate in shadow_candidates
    ]
    selected_by_symbol = {
        str(candidate.get("symbol", "")).upper(): candidate
        for candidate in list(report.get("selected_candidates", []) or [])
        if str(candidate.get("symbol", "")).strip()
    }
    selection_method = str((report.get("selection_metadata", {}) or {}).get("method") or "").strip() or None
    regime_features = {key: value for key, value in _market_regime_features(report).items() if value not in (None, "")}
    score_rank_by_key = {
        (
            str(candidate.get("symbol", "")).upper(),
            str(candidate.get("strategy_name") or "unknown"),
            bool(candidate.get("shadow_candidate")),
        ): index
        for index, candidate in enumerate(
            sorted(
                candidates,
                key=lambda item: _num(item.get("score"), 0.0) or 0.0,
                reverse=True,
            ),
            start=1,
        )
        if str(candidate.get("symbol", "")).upper()
    }
    candidate_count = len(candidates)
    for original_index, candidate in enumerate(candidates, start=1):
        symbol = str(candidate.get("symbol", "")).upper()
        if not symbol:
            continue
        candidate_has_producer_contract = "producer_agent_contract" in candidate
        candidate_producer_contract = (
            _normalize_producer_agent_contract(
                candidate.get("producer_agent_contract"),
                expected_cycle_id=source_run_id,
            )
            if candidate_has_producer_contract
            else normalized_producer_contract
        )
        features = _signal_features(candidate)
        features.update(regime_features)
        is_shadow = bool(features.get("shadow_candidate"))
        selected_candidate = None if is_shadow else selected_by_symbol.get(symbol)
        if selected_candidate:
            features["selected_for_llm"] = True
            if features.get("selection_score") is None:
                features["selection_score"] = _num(selected_candidate.get("selection_score"))
            if features.get("selection_rank") is None:
                features["selection_rank"] = selected_candidate.get("selection_rank")
            if not features.get("selection_reason"):
                features["selection_reason"] = selected_candidate.get("selection_reason")
        else:
            features["selected_for_llm"] = False
        if selection_method:
            features["selection_method"] = selection_method
        score_rank = score_rank_by_key.get(
            (
                symbol,
                str(candidate.get("strategy_name") or "unknown"),
                is_shadow,
            )
        )
        features["source_rank"] = original_index
        features["score_rank"] = score_rank
        features["source_candidate_count"] = candidate_count
        features["score_rank_percentile"] = (
            round(score_rank / candidate_count, 4)
            if score_rank is not None and candidate_count
            else None
        )
        signal_date = _date(features.get("last_date"))
        identity_key = canonical_signal_id(source, candidate)
        ambiguous_identity = identity_key in ambiguous_keys
        identity = identity_by_key.get(identity_key) or {}
        signal_id = str(candidate.get("signal_id") or identity.get("signal_id") or identity_key)
        row_source_run_id = f"{source_run_id}:shadow" if is_shadow else source_run_id
        capture = identity.get("signal_capture") if not ambiguous_identity else None
        features.update({
            "candidate_id": None if ambiguous_identity else candidate.get("candidate_id"),
            "signal_id": signal_id,
            "signal_source_run_id": None if ambiguous_identity else candidate.get("signal_source_run_id") or source_run_id,
            "signal_capture_id": None if ambiguous_identity else candidate.get("signal_capture_id"),
            "signal_date": signal_date,
            "signal_strategy_name": None if ambiguous_identity else candidate.get("signal_strategy_name") or candidate.get("strategy_name"),
            "signal_strategy_version": None if ambiguous_identity else candidate.get("signal_strategy_version") or candidate.get("strategy_version"),
            "signal_identity_status": "ambiguous" if ambiguous_identity else ("verified" if capture else "unavailable"),
            "producer_agent_attribution_status": (
                "verified" if candidate_producer_contract is not None else "unavailable"
            ),
        })
        if candidate_producer_contract is not None:
            features["producer_agent_contract"] = dict(candidate_producer_contract)
        elif candidate_has_producer_contract:
            features.pop("producer_agent_contract", None)
            report.setdefault("warnings", []).append("producer_agent_identity_unavailable")
        if capture and not ambiguous_identity:
            features["signal_identity"] = signal_identity_block(capture)
        rows.append(
            {
                "signal_id": signal_id,
                "source_run_id": row_source_run_id,
                "source": source,
                "symbol": symbol,
                "signal_date": signal_date,
                "decision": "candidate",
                "features": features,
                "gate": {},
                "outcome": {},
            }
        )
        capture_requests.append((rows[-1], candidate, candidate_producer_contract))
    try:
        if hasattr(store, "save_signal_outcomes_bulk"):
            store.save_signal_outcomes_bulk(rows)
        else:
            for row in rows:
                store.save_signal_outcome(**row)
    except Exception as exc:  # noqa: BLE001 - identity telemetry must fail open.
        report.setdefault("warnings", []).append("signal_identity_persistence_failed")
        LOGGER.warning("No se pudo persistir la identidad prospectiva: %s", exc, exc_info=True)
        return 0
    _persist_signal_prediction_captures(store, report, capture_requests)
    return len(rows)


def _signal_report_date(report: dict[str, Any]) -> str:
    report_date = _date(report.get("as_of") or report.get("session_date") or report.get("date"))
    if report_date:
        return report_date
    candidates = list(report.get("all_candidates", []) or [])
    if candidates:
        return _date(candidates[0].get("last_date"))
    return ""


def _inferred_selected_candidates(report: dict[str, Any], settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    top_longs = list(report.get("top_longs", []) or [])
    top_shorts = list(report.get("top_shorts", []) or [])
    long_limit = max(12, int(settings.news_sentiment_top_n), int(settings.trade_selection_top_n))
    short_limit = max(1, int(settings.news_sentiment_top_n // 2))
    selected = top_longs[:long_limit]
    if settings.allow_short_selling:
        selected = [*selected, *top_shorts[:short_limit]]
    metadata = {
        "method": "backfill_inferred_from_top_lists",
        "inferred": True,
        "long_limit": long_limit,
        "short_limit": short_limit if settings.allow_short_selling else 0,
    }
    return selected, metadata


def backfill_signal_candidates_from_reports(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    *,
    since_date: str | None = None,
    end_date: str | None = None,
    source: str = "closed_market_study_backfill",
    infer_selected: bool = True,
) -> dict[str, Any]:
    reports = sorted(reports_dir.glob("closed_market_technical_study_*.json"))
    saved_reports = 0
    saved_signals = 0
    inferred_reports = 0
    skipped_reports = 0
    warnings: list[str] = []

    for path in reports:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - best-effort historical recovery.
            skipped_reports += 1
            warnings.append(f"{path.name}: {exc}")
            continue
        if not isinstance(report, dict):
            skipped_reports += 1
            warnings.append(f"{path.name}: formato no soportado")
            continue
        if not report.get("run_id") or not list(report.get("all_candidates", []) or []):
            skipped_reports += 1
            continue

        report_date = _signal_report_date(report)
        if since_date and report_date and report_date < since_date:
            continue
        if end_date and report_date and report_date > end_date:
            continue

        payload = dict(report)
        if infer_selected and not list(payload.get("selected_candidates", []) or []):
            selected, metadata = _inferred_selected_candidates(payload, settings)
            if selected:
                payload["selected_candidates"] = selected
                payload["selection_metadata"] = metadata
                inferred_reports += 1

        saved = record_signal_candidates(store, payload, source=source)
        if saved <= 0:
            skipped_reports += 1
            continue
        saved_reports += 1
        saved_signals += saved

    return {
        "reports_scanned": len(reports),
        "reports_saved": saved_reports,
        "signals_saved": saved_signals,
        "inferred_reports": inferred_reports,
        "skipped_reports": skipped_reports,
        "since_date": since_date,
        "end_date": end_date,
        "source": source,
        "warnings": warnings[:50],
    }


def _gate_by_symbol(items: list[dict[str, Any]], name: str) -> dict[str, dict[str, Any]]:
    result = {}
    for item in items or []:
        result[str(item.get("symbol", "")).upper()] = {
            name: {
                "approved": item.get("approved"),
                "reason": item.get("reason"),
                "checks": item.get("checks") or item.get("metrics") or {},
            }
        }
    return result


def update_signal_decisions(
    store: Store,
    *,
    source_run_id: str | None,
    recommendations: list[TradeRecommendation],
    entry_quality_gate: list[dict[str, Any]],
    backtest_gate: list[dict[str, Any]],
    settings: Settings | None = None,
) -> int:
    if not source_run_id:
        return 0
    settings = settings or Settings()
    gate_by_symbol = defaultdict(dict)
    for symbol, gate in _gate_by_symbol(entry_quality_gate, "entry_quality_gate").items():
        gate_by_symbol[symbol].update(gate)
    for symbol, gate in _gate_by_symbol(backtest_gate, "backtest_gate").items():
        gate_by_symbol[symbol].update(gate)

    updated = 0
    for recommendation in recommendations:
        symbol = recommendation.symbol.upper()
        decision_lineage = dict(getattr(recommendation, "decision_lineage", {}) or {})
        signal_id = str(decision_lineage.get("signal_id") or "").strip() or None
        decision = recommendation.action
        gate = dict(gate_by_symbol.get(symbol, {}))
        backtest = gate.get("backtest_gate")
        if recommendation.action == "buy":
            entry_gate = gate.get("entry_quality_gate")
            entry_score = ((entry_gate or {}).get("checks") or {}).get("entry_score_v2") or {}
            # Bug telemetria: un rechazo de entry-quality no debe etiquetarse como
            # aprobado solo porque la recomendacion arrastre micro_experiment desde el
            # soft-override de backtest. El bloqueo de entry-quality solo se exime si la
            # propia entry-quality concede micro (entry_score.micro_experiment).
            entry_origin_micro = bool(entry_score.get("micro_experiment"))
            entry_micro = bool(entry_score.get("micro_experiment") or recommendation.micro_experiment)
            if entry_gate and not entry_gate.get("approved") and not entry_origin_micro:
                decision = "blocked_entry_quality"
            elif backtest and not backtest.get("approved"):
                if _paper_backtest_soft_override(settings, recommendation, gate):
                    decision = "approved_buy_soft_backtest"
                    gate["backtest_soft_override"] = {
                        "approved": True,
                        "reason": "paper_high_conviction_micro_override",
                    }
                else:
                    decision = "blocked_backtest"
                    shadow = _backtest_near_miss_shadow(settings, backtest)
                    if shadow:
                        gate["backtest_near_miss_shadow"] = shadow
            elif entry_micro:
                decision = "approved_buy_micro"
            else:
                decision = "approved_buy"
        feature_updates = {
            "recommendation_source": getattr(recommendation, "source", "llm"),
            "decision_origin": getattr(recommendation, "decision_origin", None),
            "capacity_fill_reason_code": getattr(recommendation, "capacity_fill_reason_code", None),
            "low_sample_exploration": bool(
                LOW_SAMPLE_EXPLORATION_TAG in list(getattr(recommendation, "tags", []) or [])
                or LOW_SAMPLE_EXPLORATION_TAG in list(getattr(recommendation, "soft_override_reasons", []) or [])
                or str(((backtest or {}).get("checks") or {}).get("mode") or "") == "learning_low_sample_exception"
            ),
            "tags": list(getattr(recommendation, "tags", []) or []),
            "decision_lineage": {
                **dict(getattr(recommendation, "decision_lineage", {}) or {}),
                "low_sample_exploration": bool(
                    LOW_SAMPLE_EXPLORATION_TAG in list(getattr(recommendation, "tags", []) or [])
                    or LOW_SAMPLE_EXPLORATION_TAG
                    in list(getattr(recommendation, "soft_override_reasons", []) or [])
                    or str(((backtest or {}).get("checks") or {}).get("mode") or "")
                    == "learning_low_sample_exception"
                ),
            },
            "candidate_id": ((getattr(recommendation, "decision_lineage", {}) or {}).get("candidate_id")),
            "llm_response_status": "failed"
            if (
                getattr(recommendation, "decision_origin", None) == "deterministic_fallback_llm_failed"
                or getattr(recommendation, "capacity_fill_reason_code", None) == "capacity_fill_por_fallo_llm"
            )
            else "ok",
        }
        # A control set may be retained on the recommendation when its
        # treatment is not linked to an exact signal row, but it must not be
        # written into a signal with a broken/unavailable identity link.
        control_set = dict(getattr(recommendation, "comparable_control_set", {}) or {})
        snapshot = dict(getattr(recommendation, "decision_context_snapshot", {}) or {})
        if control_set and snapshot.get("signal_link_status") == "verified":
            feature_updates["comparable_control_set"] = control_set
        gate_updates = {
            **gate,
            "llm": {
                "action": recommendation.action,
                "confidence": recommendation.confidence,
                "reason": recommendation.reason,
            },
        }
        try:
            applied = store.update_signal_decision(
                source_run_id=source_run_id,
                symbol=symbol,
                decision=decision,
                features=feature_updates,
                gate=gate_updates,
                signal_id=signal_id,
            )
        except TypeError:
            if signal_id:
                raise
            applied = store.update_signal_decision(
                source_run_id=source_run_id,
                symbol=symbol,
                decision=decision,
                gate=gate_updates,
            )
        if applied is not False:
            updated += 1
    return updated


def attach_comparable_control_sets(
    store: Store,
    *,
    recommendations: list[Any],
) -> dict[str, int]:
    """Attach captured controls without reapplying a decision or gate."""

    counts = {"attached": 0, "idempotent": 0, "conflict": 0, "unavailable": 0}
    for recommendation in recommendations:
        control_set = dict(getattr(recommendation, "comparable_control_set", {}) or {})
        snapshot = dict(getattr(recommendation, "decision_context_snapshot", {}) or {})
        lineage = dict(getattr(recommendation, "decision_lineage", {}) or {})
        signal_id = str(lineage.get("signal_id") or "").strip()
        if not control_set or snapshot.get("signal_link_status") != "verified" or not signal_id:
            continue
        result = store.attach_comparable_control_set(signal_id, control_set)
        counts[result] = counts.get(result, 0) + 1
    return counts


def attach_gate_evaluation_snapshots(
    store: Store,
    *,
    snapshots: list[dict[str, Any]],
) -> dict[str, int]:
    """Persist gate paths only for exact, verified signal identities."""

    counts = {"attached": 0, "idempotent": 0, "conflict": 0, "unavailable": 0, "skipped": 0}
    for snapshot in snapshots:
        if snapshot.get("identity_status") != "verified" or not snapshot.get("signal_id"):
            counts["skipped"] += 1
            continue
        result = store.attach_gate_evaluation_snapshot(str(snapshot["signal_id"]), snapshot)
        counts[result] = counts.get(result, 0) + 1
    return counts


_BACKTEST_NEAR_MISS_SHADOW_RULES = {
    "hit-rate 44.00% < minimo 45.00%": "hit_rate_44_vs_45",
    "trade-window alpha -0.15% < minimo 0.00%": "trade_window_alpha_minus_0_15",
    "trades 8 < minimo 10": "trades_8_vs_10",
}


def _backtest_near_miss_shadow(settings: Settings, backtest_gate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not settings.backtest_gate_near_miss_shadow_enabled or not backtest_gate:
        return None
    reason = str(backtest_gate.get("reason") or "").strip()
    rule_id = _BACKTEST_NEAR_MISS_SHADOW_RULES.get(reason)
    if not rule_id:
        return None
    return {
        "enabled": True,
        "rule_id": rule_id,
        "reason": reason,
        "mode": "shadow_only",
        "action": "track_forward_outcome_without_relaxing_gate",
    }


def _carrier_signal_id(item: Any) -> str | None:
    if isinstance(item, dict):
        direct = item.get("signal_id")
        lineage = item.get("decision_lineage") or {}
    else:
        direct = None
        lineage = getattr(item, "decision_lineage", {}) or {}
    value = str(direct or lineage.get("signal_id") or "").strip()
    return value or None


def _carrier_lineage(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item.get("decision_lineage") or {})
    return dict(getattr(item, "decision_lineage", {}) or {})


def _carrier_agent_contract(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        snapshot = item.get("decision_context_snapshot") or {}
    else:
        snapshot = getattr(item, "decision_context_snapshot", {}) or {}
    contract = snapshot.get("agent_contract") if isinstance(snapshot, dict) else None
    return dict(contract) if isinstance(contract, dict) else None


def _carrier_producer_agent_contract(item: Any) -> dict[str, Any] | None:
    lineage = _carrier_lineage(item)
    contract = lineage.get("producer_agent_contract")
    return dict(contract) if isinstance(contract, dict) else None


def update_signal_execution_status(
    store: Store,
    *,
    source_run_id: str | None,
    approved_symbols: list[str] | None = None,
    approved_recommendations: list[Any] | None = None,
    rejected_order_plans: list[dict[str, Any]] | None = None,
    planned_symbols: list[str] | None = None,
    planned_signal_ids: list[str] | None = None,
    submitted: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
    effective_max_orders_per_cycle: int | None = None,
    effective_max_daily_buy_orders: int | None = None,
    cycle_id: str | None = None,
) -> int:
    if not source_run_id:
        return 0

    rejected_by_symbol: dict[str, dict[str, Any]] = {}
    for item in rejected_order_plans or []:
        symbol = str(item.get("symbol") or "").upper().strip()
        if symbol and symbol not in rejected_by_symbol:
            rejected_by_symbol[symbol] = item
    submitted_by_symbol = {
        str(item.get("symbol") or "").upper().strip(): item
        for item in (submitted or [])
        if str(item.get("symbol") or "").strip()
    }
    failed_by_symbol = {
        str(item.get("symbol") or "").upper().strip(): item
        for item in (failed or [])
        if str(item.get("symbol") or "").strip()
    }
    rejected_by_signal_id = {
        str(item.get("signal_id") or "").strip(): item
        for item in (rejected_order_plans or [])
        if str(item.get("signal_id") or "").strip()
    }
    submitted_by_signal_id = {
        _carrier_signal_id(item): item
        for item in (submitted or [])
        if _carrier_signal_id(item)
    }
    failed_by_signal_id = {
        _carrier_signal_id(item): item
        for item in (failed or [])
        if _carrier_signal_id(item)
    }
    exact_planned_signal_ids = {
        str(item or "").strip() for item in (planned_signal_ids or []) if str(item or "").strip()
    }
    planned = {str(symbol).upper().strip() for symbol in (planned_symbols or []) if str(symbol).strip()}
    updated = 0

    def _payload_for(
        *,
        signal_id: str | None = None,
        lineage: dict[str, Any] | None = None,
        agent_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "effective_max_orders_per_cycle": effective_max_orders_per_cycle,
            "effective_max_daily_buy_orders": effective_max_daily_buy_orders,
            "source_run_id": source_run_id,
        }
        if cycle_id:
            payload["cycle_id"] = cycle_id
        if signal_id:
            payload["signal_id"] = signal_id
        if lineage:
            payload["decision_lineage"] = dict(lineage)
        if agent_contract:
            payload["agent_contract"] = dict(agent_contract)
        return payload

    def _apply_exact(recommendation: Any) -> None:
        nonlocal updated
        symbol = str(getattr(recommendation, "symbol", "") or "").upper().strip()
        signal_id = _carrier_signal_id(recommendation)
        if not symbol or not signal_id:
            return
        lineage = _carrier_lineage(recommendation)
        payload = _payload_for(
            signal_id=signal_id,
            lineage=lineage,
            agent_contract=_carrier_agent_contract(recommendation),
        )
        producer_contract = _carrier_producer_agent_contract(recommendation)
        if producer_contract:
            payload["producer_agent_contract"] = producer_contract
        if signal_id in submitted_by_signal_id:
            item = submitted_by_signal_id[signal_id]
            payload.update(
                {
                    "status": "submitted",
                    "broker_status": item.get("status"),
                    "notional": item.get("notional"),
                }
            )
        elif signal_id in failed_by_signal_id:
            item = failed_by_signal_id[signal_id]
            payload.update(
                {
                    "status": "submit_failed",
                    "side": item.get("side"),
                    "error": item.get("error"),
                }
            )
        elif signal_id in rejected_by_signal_id:
            item = rejected_by_signal_id[signal_id]
            payload.update(
                {
                    "status": "plan_rejected",
                    "stage": item.get("stage"),
                    "reason": item.get("reason"),
                    "checks": item.get("checks", {}),
                }
            )
        elif signal_id in exact_planned_signal_ids:
            payload["status"] = "plan_created"
        else:
            payload.update(
                {
                    "status": "approved_not_planned",
                    "reason": "approved_not_planned",
                }
            )
        if store.update_signal_gate(
            source_run_id=source_run_id,
            symbol=symbol,
            signal_id=signal_id,
            gate={"execution": payload},
        ):
            updated += 1

    if approved_recommendations is not None:
        for recommendation in approved_recommendations:
            _apply_exact(recommendation)
        return updated

    for raw_symbol in approved_symbols or []:
        symbol = str(raw_symbol or "").upper().strip()
        if not symbol:
            continue
        payload = {
            "effective_max_orders_per_cycle": effective_max_orders_per_cycle,
            "effective_max_daily_buy_orders": effective_max_daily_buy_orders,
            "source_run_id": source_run_id,
        }
        if cycle_id:
            payload["cycle_id"] = cycle_id
        if symbol in submitted_by_symbol:
            item = submitted_by_symbol[symbol]
            payload.update(
                {
                    "status": "submitted",
                    "broker_status": item.get("status"),
                    "notional": item.get("notional"),
                }
            )
        elif symbol in failed_by_symbol:
            item = failed_by_symbol[symbol]
            payload.update(
                {
                    "status": "submit_failed",
                    "side": item.get("side"),
                    "error": item.get("error"),
                }
            )
        elif symbol in rejected_by_symbol:
            item = rejected_by_symbol[symbol]
            payload.update(
                {
                    "status": "plan_rejected",
                    "stage": item.get("stage"),
                    "reason": item.get("reason"),
                    "checks": item.get("checks", {}),
                }
            )
        elif symbol in planned:
            payload["status"] = "plan_created"
        else:
            payload["status"] = "approved_not_planned"
        store.update_signal_gate(
            source_run_id=source_run_id,
            symbol=symbol,
            gate={"execution": payload},
        )
        updated += 1
    return updated


def _paper_backtest_soft_override(
    settings: Settings,
    recommendation: TradeRecommendation,
    gate: dict[str, Any],
) -> bool:
    if not settings.backtest_gate_paper_soft_override_enabled:
        return False
    if settings.trading_mode != "paper":
        return False
    if settings.trade_aggressiveness_profile not in {"opportunistic", "aggressive"}:
        return False
    if recommendation.backtest_soft_override or "backtest_soft_override_eligible" in list(
        recommendation.soft_override_reasons or []
    ):
        return True
    entry_gate = gate.get("entry_quality_gate") or {}
    entry_checks = entry_gate.get("checks") or {}
    entry_score = entry_checks.get("entry_score_v2") or {}
    if entry_gate and not entry_gate.get("approved") and not entry_score.get("micro_experiment"):
        return False

    reward_risk = _num(entry_score.get("reward_risk"))
    score = _num(entry_checks.get("score"), 0.0)
    volume_z = _num(entry_checks.get("volume_zscore_20"), 0.0)
    close_position = _num(entry_checks.get("close_position_in_range"), 0.0)
    sma20_distance = _num(entry_checks.get("sma20_distance"))
    rsi = _num(entry_checks.get("rsi_14"))
    confirmed = int(entry_checks.get("confirmed_bullish_patterns") or 0)
    sentiment_score = _num(entry_checks.get("sentiment_score"))
    sentiment_confidence = _num(entry_checks.get("sentiment_confidence"), 0.0) or 0.0
    confirmed_negative_sentiment = (
        sentiment_score is not None
        and sentiment_confidence >= 0.5
        and sentiment_score <= -0.5
    )

    return bool(
        (score or 0.0) >= 16
        and (volume_z or 0.0) >= 1.25
        and confirmed >= 1
        and reward_risk is not None
        and reward_risk >= 1.5
        and (close_position or 0.0) >= 0.80
        and (sma20_distance is None or sma20_distance <= 0.26)
        and (rsi is None or rsi <= 88.0)
        and not confirmed_negative_sentiment
    )


def _symbol_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _bar_date(index: Any) -> str:
    if hasattr(index, "date"):
        return str(index.date())
    return str(index)[:10]


def last_completed_session(
    *, now: datetime | None = None, calendar: Any | None = None
) -> tuple[str | None, bool]:
    """Last XNYS session with market_close <= now (P-L137).

    Returns (session_date_iso | None, degraded). Degraded means the
    exchange calendar was unavailable and a weekday rule applied, which
    ignores holidays.
    """

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    resolved = calendar
    if resolved is None:
        try:
            from agente_bolsa.market_calendar import MarketCalendar

            resolved = MarketCalendar()
        except Exception:  # noqa: BLE001 - degraded fallback below.
            resolved = None
    if resolved is not None:
        try:
            schedule = resolved.session_schedule(
                start_date=(now_utc.date() - timedelta(days=14)).isoformat(),
                end_date=now_utc.date().isoformat(),
            )
        except Exception:  # noqa: BLE001 - degraded fallback below.
            schedule = None
        if schedule is not None and not schedule.empty:
            closes = pd.to_datetime(schedule["market_close"], utc=True)
            done = schedule.index[closes <= now_utc]
            if len(done):
                stamp = done.max()
                day = stamp.date().isoformat() if hasattr(stamp, "date") else str(stamp)[:10]
                return day, False
            return None, False
    market_now = now_utc.astimezone(ZoneInfo("America/New_York"))
    day = market_now.date()
    if not (day.weekday() < 5 and market_now.time() >= time(16, 0)):
        shift = 1
        while (day - timedelta(days=shift)).weekday() >= 5:
            shift += 1
        day = day - timedelta(days=shift)
    return day.isoformat(), True


def trim_to_completed_sessions(
    frame: pd.DataFrame, *, now: datetime | None = None, calendar: Any | None = None
) -> tuple[pd.DataFrame, int, str | None, bool]:
    """Drop bars dated after the last completed session (P-L137).

    A same-day (still open) bar is mutable: counting it as matured
    forward history repeats the SPY same-day-finality bug (P-L71/P-L127)
    on universe bars. Returns (kept_frame, trimmed, last_session, degraded).
    """

    last_completed, degraded = last_completed_session(now=now, calendar=calendar)
    if frame.empty or last_completed is None:
        return frame, 0, last_completed, True if last_completed is None else degraded
    keep = frame.index.map(_bar_date) <= last_completed
    kept = frame.loc[keep]
    return kept, int(len(frame) - len(kept)), last_completed, degraded


def _outcome_for_signal(signal: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    features = signal.get("features", {}) or {}
    entry = _num(features.get("entry_price") or features.get("close"))
    stop = _num(features.get("stop_loss"))
    take = _num(features.get("take_profit"))
    if not entry:
        return {"available": False, "reason": "sin entry_price"}

    signal_date = signal["signal_date"]
    bar_dates = frame.index.map(_bar_date)
    future = frame.loc[bar_dates > signal_date].copy()
    if future.empty:
        return {
            "available": False,
            "matured": False,
            "bars_seen": 0,
            "matured_horizons": {f"{h}d": False for h in HORIZONS},
            "reason": "sin barras posteriores",
        }

    closes = [_num(value) for value in future["Close"].tolist()]
    highs = [_num(value) for value in future["High"].tolist()]
    lows = [_num(value) for value in future["Low"].tolist()]
    dates = [_bar_date(index) for index in future.index]
    returns = {}
    matured_horizons = {}
    for horizon in HORIZONS:
        # A horizon is mature only when every close through that point is
        # present.  A missing bar cannot be silently skipped or converted to
        # a mature outcome by looking farther into the future.
        if len(closes) >= horizon and all(value is not None for value in closes[:horizon]):
            returns[f"return_{horizon}d"] = round((closes[horizon - 1] - entry) / entry, 4)
            matured_horizons[f"{horizon}d"] = True
        else:
            returns[f"return_{horizon}d"] = None
            matured_horizons[f"{horizon}d"] = False

    window_highs = [value for value in highs[:10] if value is not None]
    window_lows = [value for value in lows[:10] if value is not None]
    first_hit = None
    for index, (date, high, low) in enumerate(
        zip(dates[:10], highs[:10], lows[:10], strict=False),
        start=1,
    ):
        if low is not None and stop is not None and low <= stop:
            first_hit = {"type": "stop_loss", "date": date, "days": index}
            break
        if high is not None and take is not None and high >= take:
            first_hit = {"type": "take_profit", "date": date, "days": index}
            break

    outcome = {
        "available": True,
        "matured": bool(matured_horizons.get(f"{max(HORIZONS)}d")),
        "bars_seen": len(closes),
        "matured_horizons": matured_horizons,
        "as_of": datetime.now(timezone.utc).isoformat(),
        **returns,
        "mfe_10d": round((max(window_highs) - entry) / entry, 4) if window_highs else None,
        "mae_10d": round((min(window_lows) - entry) / entry, 4) if window_lows else None,
        "first_hit": first_hit,
        "exit_policy_v2": _simulate_exit_policy_v2(
            entry=entry,
            stop=stop,
            take=take,
            closes=closes,
            highs=highs,
            lows=lows,
            dates=dates,
        ),
    }
    outcome["verdict"] = _verdict(outcome)
    return outcome


def _simulate_exit_policy_v2(
    *,
    entry: float,
    stop: float | None,
    take: float | None,
    closes: list[float | None],
    highs: list[float | None],
    lows: list[float | None],
    dates: list[str],
    partial_r: float = 1.0,
    trailing_r: float = 2.0,
    trailing_giveback_r: float = 1.0,
    time_stop_days: int = 5,
    time_stop_min_return: float = 0.0,
    stale_guard_enabled: bool = False,
    stale_guard_days: int = 10,
    stale_guard_max_peak_return: float = 0.05,
    stale_guard_min_return: float = 0.01,
) -> dict[str, Any]:
    if not entry or not closes:
        return {"available": False, "reason": "sin barras"}
    initial_risk = entry - stop if stop is not None and stop < entry else None
    if initial_risk is None or initial_risk <= 0:
        initial_risk = entry * 0.05
    partial_taken = False
    peak_price = entry
    trailing_stop = stop
    events: list[dict[str, Any]] = []
    exit_price = closes[min(len(closes), 10) - 1] or entry
    exit_reason = "horizon_10d" if len(closes) >= 10 else "pending"
    exit_day = min(len(closes), 10)
    max_window = min(len(closes), 10)
    for index in range(max_window):
        day = index + 1
        date = dates[index] if index < len(dates) else ""
        high = highs[index]
        low = lows[index]
        close = closes[index]
        if high is not None:
            peak_price = max(peak_price, high)
        if not partial_taken and high is not None and high >= entry + (partial_r * initial_risk):
            partial_taken = True
            events.append(
                {
                    "type": "partial_take_profit",
                    "date": date,
                    "days": day,
                    "price": round(entry + (partial_r * initial_risk), 4),
                    "fraction": 0.5,
                }
            )
        if high is not None and high >= entry + (trailing_r * initial_risk):
            candidate_stop = peak_price - (trailing_giveback_r * initial_risk)
            trailing_stop = max(trailing_stop or 0.0, candidate_stop)
        active_stop = trailing_stop or stop
        if low is not None and active_stop is not None and low <= active_stop:
            exit_price = active_stop
            exit_reason = "trailing_stop" if trailing_stop and trailing_stop != stop else "stop_loss"
            exit_day = day
            events.append({"type": exit_reason, "date": date, "days": day, "price": round(exit_price, 4)})
            break
        if high is not None and take is not None and high >= take:
            exit_price = take
            exit_reason = "take_profit"
            exit_day = day
            events.append({"type": "take_profit", "date": date, "days": day, "price": round(exit_price, 4)})
            break
        if day >= time_stop_days and close is not None and ((close - entry) / entry) <= time_stop_min_return:
            exit_price = close
            exit_reason = "time_stop"
            exit_day = day
            events.append({"type": "time_stop", "date": date, "days": day, "price": round(exit_price, 4)})
            break
        if (
            stale_guard_enabled
            and day >= stale_guard_days
            and close is not None
            and ((peak_price - entry) / entry) <= stale_guard_max_peak_return
            and ((close - entry) / entry) <= stale_guard_min_return
        ):
            exit_price = close
            exit_reason = "stale_guard"
            exit_day = day
            events.append({"type": "stale_guard", "date": date, "days": day, "price": round(exit_price, 4)})
            break
    gross_return = (exit_price - entry) / entry
    if partial_taken and exit_reason not in {"pending"}:
        partial_price = entry + (partial_r * initial_risk)
        gross_return = (((partial_price - entry) / entry) * 0.5) + (((exit_price - entry) / entry) * 0.5)
    # Retorno neto de slippage sintetico (T5.5), aditivo: no altera return_pct
    # (que sigue siendo el bruto) para no romper metricas/tests existentes.
    from .cost_calibration import apply_synthetic_slippage

    net_return = apply_synthetic_slippage(gross_return, slippage_bps=10)
    return {
        "available": True,
        "exit_reason": exit_reason,
        "exit_day": exit_day,
        "exit_price": round(exit_price, 4),
        "return_pct": round(gross_return, 4),
        "gross_return_pct": round(gross_return, 4),
        "net_return_pct": round(net_return, 4),
        "partial_taken": partial_taken,
        "peak_return": round((peak_price - entry) / entry, 4),
        "events": events,
        "parameters": {
            "partial_r": partial_r,
            "trailing_r": trailing_r,
            "trailing_giveback_r": trailing_giveback_r,
            "time_stop_days": time_stop_days,
            "time_stop_min_return": time_stop_min_return,
            "stale_guard_enabled": stale_guard_enabled,
            "stale_guard_days": stale_guard_days,
            "stale_guard_max_peak_return": stale_guard_max_peak_return,
            "stale_guard_min_return": stale_guard_min_return,
        },
    }


def _verdict(outcome: dict[str, Any]) -> str:
    if not outcome.get("matured") and not (outcome.get("first_hit") or {}).get("type"):
        return "pending"
    first_hit = outcome.get("first_hit") or {}
    if first_hit.get("type") == "take_profit":
        return "winner_take_profit"
    if first_hit.get("type") == "stop_loss":
        return "loser_stop_loss"
    ret_5d = outcome.get("return_5d")
    ret_10d = outcome.get("return_10d")
    ref = ret_10d if ret_10d is not None else ret_5d
    if ref is None:
        return "pending"
    if ref > 0.01:
        return "winner_open"
    if ref < -0.01:
        return "loser_open"
    return "flat"


def update_signal_outcomes(
    settings: Settings,
    store: Store,
    *,
    limit: int = 1000,
    since_date: str = "2026-04-01",
    now: datetime | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    signals = store.signal_outcomes(
        limit=limit,
        since_date=since_date,
        include_lab_book=True,
        include_learning_experiment=True,
    )
    symbols = sorted({signal["symbol"] for signal in signals})
    if not signals or not symbols:
        return {"updated": 0, "signals": 0, "symbols": 0, "warnings": [],
                "bars_trimmed_universe": 0, "last_completed_session": None,
                "session_seal_degraded": None}
    start = min(signal["signal_date"] for signal in signals)
    end = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    warnings = []
    try:
        data = download_daily_prices(symbols, start=start, end=end)
    except Exception as exc:  # noqa: BLE001
        return {"updated": 0, "signals": len(signals), "symbols": len(symbols), "warnings": [str(exc)],
                "bars_trimmed_universe": 0, "last_completed_session": None,
                "session_seal_degraded": None}
    data, bars_trimmed, last_completed, seal_degraded = trim_to_completed_sessions(data, now=now)

    updated = 0
    outcome_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    frame_by_symbol: dict[str, pd.DataFrame] = {}
    outcomes_to_save: dict[str, dict[str, Any]] = {}
    for signal in signals:
        try:
            symbol = signal["symbol"]
            if symbol not in frame_by_symbol:
                frame_by_symbol[symbol] = _symbol_frame(data, symbol).dropna(how="all")
            frame = frame_by_symbol[symbol]
            if frame.empty:
                continue
            features = signal.get("features", {}) or {}
            cache_key = (
                signal["symbol"],
                signal["signal_date"],
                _num(features.get("entry_price") or features.get("close")),
                _num(features.get("stop_loss")),
                _num(features.get("take_profit")),
            )
            outcome = outcome_cache.get(cache_key)
            if outcome is None:
                outcome = _outcome_for_signal(signal, frame)
                outcome_cache[cache_key] = outcome
            outcomes_to_save[signal["signal_id"]] = outcome
            updated += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{signal['symbol']}: {exc}")
    if hasattr(store, "update_signal_outcomes_bulk"):
        store.update_signal_outcomes_bulk(outcomes_to_save)
    else:
        for signal_id, outcome in outcomes_to_save.items():
            store.update_signal_outcome(signal_id, outcome)
    try:
        observation_ok = _persist_signal_outcome_captures(
            settings,
            store,
            signals,
            data,
            observed_at=observed_at or datetime.now(timezone.utc),
        )
        if not observation_ok:
            warnings.append("prospective_capture_observation_failed")
    except Exception:  # noqa: BLE001 - prospective telemetry remains fail-open.
        warnings.append("prospective_capture_observation_failed")
        LOGGER.exception("FallÃ³ observaciÃ³n prospectiva; se conserva outcome legacy")
    return {"updated": updated, "signals": len(signals), "symbols": len(symbols), "warnings": warnings[:20],
            "bars_trimmed_universe": bars_trimmed, "last_completed_session": last_completed,
            "session_seal_degraded": seal_degraded}


def _bucket(value: Any, buckets: list[tuple[str, float, float]]) -> str:
    number = _num(value)
    if number is None:
        return "unknown"
    for label, low, high in buckets:
        if low <= number < high:
            return label
    return buckets[-1][0]


def _indicator_tags(signal: dict[str, Any]) -> list[str]:
    if isinstance(signal, _LearningMetricSignal):
        return signal.indicator_tags
    features = signal.get("features", {}) or {}
    chart = features.get("chart_patterns", {}) or {}
    tags = [
        f"score:{_bucket(features.get('score'), [('lt12', -999, 12), ('12_14', 12, 15), ('gte15', 15, 999)])}",
        f"rsi:{_bucket(features.get('rsi_14'), [('lt60', -999, 60), ('60_75', 60, 75), ('75_85', 75, 85), ('gt85', 85, 999)])}",
        f"sma20_dist:{_bucket(features.get('distance_sma20'), [('lt0', -999, 0), ('0_6pct', 0, 0.06), ('6_12pct', 0.06, 0.12), ('gt12pct', 0.12, 999)])}",
        f"macd:{'positive' if _num(features.get('macd_diff'), 0) and _num(features.get('macd_diff'), 0) > 0 else 'non_positive'}",
        f"volume_z:{_bucket(features.get('volume_zscore_20'), [('lt0', -999, 0), ('0_1', 0, 1), ('gt1', 1, 999)])}",
        f"chart_confirmed:{'yes' if chart.get('bullish_confirmed_count', 0) else 'no'}",
    ]
    return tags


def _combo_key(signal: dict[str, Any]) -> str:
    if isinstance(signal, _LearningMetricSignal):
        return signal.combination
    features = signal.get("features", {}) or {}
    chart = features.get("chart_patterns", {}) or {}
    score = _bucket(features.get("score"), [("lt12", -999, 12), ("12_14", 12, 15), ("gte15", 15, 999)])
    rsi = _bucket(features.get("rsi_14"), [("lt60", -999, 60), ("60_75", 60, 75), ("75_85", 75, 85), ("gt85", 85, 999)])
    dist = _bucket(
        features.get("distance_sma20"),
        [("lt0", -999, 0), ("0_6pct", 0, 0.06), ("6_12pct", 0.06, 0.12), ("gt12pct", 0.12, 999)],
    )
    macd = "macd_pos" if _num(features.get("macd_diff"), 0) and _num(features.get("macd_diff"), 0) > 0 else "macd_nonpos"
    volume = _bucket(features.get("volume_zscore_20"), [("vol_lt0", -999, 0), ("vol_0_1", 0, 1), ("vol_gt1", 1, 999)])
    pattern = "pattern_yes" if chart.get("bullish_confirmed_count", 0) else "pattern_no"
    return "|".join([f"score_{score}", f"rsi_{rsi}", f"sma20_{dist}", macd, volume, pattern])


def _setup_key(signal: dict[str, Any]) -> str:
    if isinstance(signal, _LearningMetricSignal):
        return signal.setup
    features = signal.get("features", {}) or {}
    if bool(features.get("event_momentum_long")):
        return "event_momentum"
    if bool(features.get("range_expansion_breakout_long")):
        return "range_expansion_breakout"
    if bool(features.get("orderly_breakout_long")):
        return "orderly_breakout"
    if bool(features.get("momentum_shakeout_hold_long")):
        return "momentum_shakeout"
    chart = features.get("chart_patterns", {}) or {}
    if chart.get("bullish_confirmed_count", 0):
        return "confirmed_pattern"
    volume_z = _num(features.get("volume_zscore_20")) or 0.0
    return_20d = _num(features.get("return_20d")) or 0.0
    if volume_z >= 1.0 and return_20d > 0:
        return "trend_volume"
    return "baseline_trend"


def _resolved_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        signal
        for signal in signals
        if (
            (signal.get("outcome") or {}).get("verdict") not in {None, "", "pending"}
            or any((signal.get("outcome") or {}).get(f"return_{h}d") is not None for h in HORIZONS)
        )
    ]


class _LearningMetricSignal(dict[str, Any]):
    """Private projection: identity is verified before discarding large carriers."""

    agent_identity: tuple[dict[str, Any] | None, str, str]
    same_cycle_control: bool
    legacy_unverified: bool
    lineage: dict[str, str | None]
    indicator_tags: list[str]
    combination: str
    setup: str


def _compact_learning_metric_signal(signal: dict[str, Any]) -> _LearningMetricSignal:
    # Evaluate original carriers first, including conflicts in unused contract fields.
    contract, status, role = _agent_contract_from_signal(signal)
    lineage = _lineage_for_row(signal)
    control = _control_is_same_cycle_verified(signal, contract)
    legacy = _is_legacy_unverified(signal)
    features = signal.get("features", {}) or {}
    # Preserve legacy malformed-feature errors before projecting valid feature maps.
    indicator_tags = _indicator_tags(signal)
    combination = _combo_key(signal)
    setup = _setup_key(signal)
    feature_keys = ("direction", "position_direction", "exit_position_direction", "selected_for_llm")
    projected_features = {key: features[key] for key in feature_keys if key in features}
    outcome = signal.get("outcome") or {}
    outcome_keys = ("verdict", "source", "mfe_10d", "mae_10d", *(f"return_{h}d" for h in HORIZONS))
    projected_outcome = {key: outcome[key] for key in outcome_keys if key in outcome}
    maturity = outcome.get("matured_horizons")
    if "matured_horizons" in outcome:
        projected_outcome["matured_horizons"] = (
            {f"{h}d": maturity[f"{h}d"] for h in HORIZONS if f"{h}d" in maturity}
            if isinstance(maturity, dict) else maturity
        )
    gate = signal.get("gate") if isinstance(signal.get("gate"), dict) else {}
    projected_gate: dict[str, Any] = {}
    if any(bool(value) for value in gate.values()):
        projected_gate["observed"] = True
    execution = _execution_payload(signal)
    if execution is not None:
        projected_gate["execution"] = {
            key: execution[key] for key in ("signal_id", "status") if key in execution
        }
        # Stage feedback distinguishes an empty execution dict from an observed one.
        if execution and not projected_gate["execution"]:
            projected_gate["execution"]["observed"] = True
    compact = _LearningMetricSignal(
        {key: signal[key] for key in ("signal_id", "source_run_id", "decision", "direction") if key in signal},
        features=projected_features, gate=projected_gate, outcome=projected_outcome,
    )
    if contract is not None:
        keys = (
            "schema_version", "agent_name", "canonical_agent_id", "agent_run_id", "cycle_id",
            "execution_kind", "decision_source", "provider", "model", "parent_run_id", "retry_of",
            "fallback_reason", "llm_provider", "llm_effective_model",
        )
        projected_contract = {key: contract[key] for key in keys if key in contract}
        for field, fields in (("fallback", ("used", "reason")), ("effective_identity", ("provider", "model"))):
            value = contract.get(field)
            if isinstance(value, dict):
                projected_contract[field] = {key: value[key] for key in fields if key in value}
        contract = projected_contract
    compact.agent_identity = contract, status, role
    compact.lineage = lineage
    compact.same_cycle_control = control
    compact.legacy_unverified = legacy
    compact.indicator_tags = indicator_tags
    compact.combination = combination
    compact.setup = setup
    return compact


def _agent_contract_from_signal(
    signal: dict[str, Any],
) -> tuple[dict[str, Any] | None, str, str]:
    """Read exact producer/decision carriers; never infer from symbol/source."""

    if isinstance(signal, _LearningMetricSignal):
        return signal.agent_identity
    features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
    producer_candidates = [
        item
        for item in (
            features.get("producer_agent_contract"),
            ((signal.get("gate") or {}).get("execution") or {}).get("producer_agent_contract")
            if isinstance(signal.get("gate"), dict)
            else None,
        )
        if isinstance(item, dict)
    ]
    if producer_candidates:
        first = producer_candidates[0]
        if any(
            json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
            != json.dumps(first, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
            for item in producer_candidates[1:]
        ):
            return None, "conflict", "producer"
        producer = _normalize_producer_agent_contract(first)
        if producer is None:
            return None, "unavailable", "producer"
        return producer, "verified", "producer"

    snapshot = features.get("decision_context_snapshot")
    snapshot_contract = (
        snapshot.get("agent_contract")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("agent_contract"), dict)
        else None
    )
    gate = signal.get("gate") if isinstance(signal.get("gate"), dict) else {}
    execution = gate.get("execution")
    execution_contract = (
        execution.get("agent_contract")
        if isinstance(execution, dict) and isinstance(execution.get("agent_contract"), dict)
        else None
    )
    if snapshot_contract is not None and execution_contract is not None:
        snapshot_payload = json.dumps(snapshot_contract, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
        execution_payload = json.dumps(execution_contract, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
        if snapshot_payload != execution_payload:
            return None, "conflict", "decision"
    contract = execution_contract or snapshot_contract
    if not isinstance(contract, dict):
        return None, "unavailable", "decision"
    required = ("schema_version", "agent_name", "agent_run_id", "cycle_id")
    if contract.get("schema_version") != AGENT_CONTRACT_SCHEMA_VERSION:
        return None, "unavailable", "decision"
    if any(not str(contract.get(field) or "").strip() for field in required[1:]):
        return None, "unavailable", "decision"
    return dict(contract), "verified", "decision"


_LONG_DIRECTIONS = frozenset({"long", "buy", "bullish", "up"})
_SHORT_DIRECTIONS = frozenset({"short", "sell", "bearish", "down"})
_EXIT_DIRECTIONS = frozenset({"exit", "close", "flat"})


def _learning_direction(signal: dict[str, Any]) -> str | None:
    features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
    raw = features.get("direction")
    if raw in (None, ""):
        raw = signal.get("direction")
    direction = str(raw or "").strip().lower()
    if direction in _LONG_DIRECTIONS:
        return "long"
    if direction in _SHORT_DIRECTIONS:
        return "short"
    if direction in _EXIT_DIRECTIONS:
        position = features.get("position_direction") or features.get("exit_position_direction")
        position_text = str(position or "").strip().lower()
        if position_text in _LONG_DIRECTIONS:
            return "exit_long"
        if position_text in _SHORT_DIRECTIONS:
            return "exit_short"
        return "exit"
    return None


def _signed_learning_return(
    signal: dict[str, Any],
    outcome: dict[str, Any],
    horizon: int,
) -> tuple[float | None, str | None]:
    raw = _num(outcome.get(f"return_{horizon}d"))
    if raw is None:
        return None, "return_unavailable"
    direction = _learning_direction(signal)
    if direction == "long":
        return raw, None
    if direction in {"short", "exit_long"}:
        return -raw, None
    if direction == "exit_short":
        return raw, None
    if direction == "exit":
        return None, "exit_position_direction_unavailable"
    return None, "direction_unavailable"


def _mature_signed_return_with_reason(
    signal: dict[str, Any],
    outcome: dict[str, Any],
    horizon: int,
) -> tuple[float | None, str | None]:
    """Return one eligible, direction-corrected forward return.

    This is the shared eligibility boundary for policy and agent metrics.
    Trade-memory rows, immature outcomes, missing returns and missing
    direction remain explicitly unavailable.
    """

    if str(outcome.get("source") or "").strip().lower() == "trade_memory":
        return None, "trade_memory"
    maturity = outcome.get("matured_horizons")
    if not isinstance(maturity, dict) or maturity.get(f"{horizon}d") is not True:
        return None, "immature"
    return _signed_learning_return(signal, outcome, horizon)


def _learning_metric_record(signed_gross_return: float) -> dict[str, Any]:
    """Build direction-corrected metric values without changing policy."""

    net_return_10bps = signed_gross_return - LEARNING_NET_10BPS_COST
    return {
        "signed_gross_return": signed_gross_return,
        "net_return_10bps": net_return_10bps,
        "hit_rate_net_10bps": net_return_10bps > 0,
        "gross_gt_1pct": signed_gross_return > LEARNING_GROSS_HIT_THRESHOLD,
    }


def _execution_payload(signal: dict[str, Any]) -> dict[str, Any] | None:
    gate = signal.get("gate") if isinstance(signal.get("gate"), dict) else {}
    execution = gate.get("execution")
    return execution if isinstance(execution, dict) else None


def _execution_is_verified(signal: dict[str, Any]) -> bool:
    execution = _execution_payload(signal)
    signal_id = str(signal.get("signal_id") or "").strip()
    status = str((execution or {}).get("status") or "").strip()
    known_statuses = {
        "submitted",
        "submit_failed",
        "plan_rejected",
        "plan_created",
        "approved_not_planned",
    }
    return bool(
        execution
        and signal_id
        and str(execution.get("signal_id") or "").strip() == signal_id
        and status in known_statuses
    )


def _control_is_verified_exact(signal: dict[str, Any]) -> bool:
    features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
    control = features.get("comparable_control_set")
    treatment = control.get("treatment") if isinstance(control, dict) else None
    signal_id = str(signal.get("signal_id") or "").strip()
    return bool(
        isinstance(control, dict)
        and control.get("status") == "verified"
        and isinstance(treatment, dict)
        and signal_id
        and treatment.get("signal_id") == signal_id
        and str(control.get("cycle_id") or "").strip()
    )


def _control_is_same_cycle_verified(
    signal: dict[str, Any],
    contract: dict[str, Any] | None,
) -> bool:
    if isinstance(signal, _LearningMetricSignal):
        return signal.same_cycle_control
    if not _control_is_verified_exact(signal):
        return False
    features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
    control = features.get("comparable_control_set")
    contract_cycle = str((contract or {}).get("cycle_id") or "").strip()
    return bool(
        contract_cycle
        and str(control.get("cycle_id") or "").strip() == contract_cycle
    )


def _is_legacy_unverified(signal: dict[str, Any]) -> bool:
    if isinstance(signal, _LearningMetricSignal):
        return signal.legacy_unverified
    features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
    gate = signal.get("gate") if isinstance(signal.get("gate"), dict) else {}
    execution = gate.get("execution") if isinstance(gate.get("execution"), dict) else {}
    carriers = (
        signal,
        features,
        features.get("decision_lineage"),
        features.get("decision_context_snapshot"),
        features.get("execution_quality_snapshot"),
        execution,
    )
    return any(
        isinstance(item, dict) and str(item.get("lineage_status") or "").strip() == "legacy_unverified"
        for item in carriers
    )


def _execution_profile(contract: dict[str, Any], role: str) -> dict[str, Any]:
    if role == "producer":
        kind = str(contract.get("execution_kind") or "").strip()
        return {
            "kind": kind if kind in EXECUTION_KINDS else "unknown",
            "provider": str(contract.get("provider") or "").strip() or None,
            "model": str(contract.get("model") or "").strip() or None,
            "fallback_reason": str(contract.get("fallback_reason") or "").strip() or None,
        }

    source = str(contract.get("decision_source") or "").strip().lower()
    fallback = contract.get("fallback") if isinstance(contract.get("fallback"), dict) else {}
    fallback_used = fallback.get("used") is True
    if source == "fallback" or fallback_used:
        kind = "fallback"
    elif source in {"llm", "deterministic", "human", "system", "capacity_fill"}:
        kind = source
    else:
        kind = "unknown"
    effective = contract.get("effective_identity") if isinstance(contract.get("effective_identity"), dict) else {}
    return {
        "kind": kind,
        "provider": str(effective.get("provider") or contract.get("llm_provider") or "").strip() or None,
        "model": str(effective.get("model") or contract.get("llm_effective_model") or "").strip() or None,
        "fallback_reason": str(fallback.get("reason") or contract.get("fallback_reason") or "").strip() or None,
    }


def _counter_values(values: list[str | None]) -> dict[str, int]:
    counts = Counter(str(value).strip() for value in values if str(value or "").strip())
    return dict(sorted(counts.items()))


def _lineage_for_row(row: dict[str, Any]) -> dict[str, str | None]:
    """Extract only explicit, exact carriers for a feedback hypothesis."""

    if isinstance(row, _LearningMetricSignal):
        return row.lineage

    features = row.get("features") if isinstance(row.get("features"), dict) else {}
    gate = row.get("gate") if isinstance(row.get("gate"), dict) else {}
    execution = gate.get("execution") if isinstance(gate.get("execution"), dict) else {}
    decision_lineage = features.get("decision_lineage") if isinstance(features.get("decision_lineage"), dict) else {}
    snapshot = features.get("decision_context_snapshot") if isinstance(features.get("decision_context_snapshot"), dict) else {}
    execution_quality = features.get("execution_quality_snapshot") if isinstance(features.get("execution_quality_snapshot"), dict) else {}
    contract, status, _role = _agent_contract_from_signal(row)

    def first_named(name: str, *containers: dict[str, Any]) -> str | None:
        for container in containers:
            candidate = str(container.get(name) or "").strip()
            if candidate:
                return candidate
        return None

    return {
        "signal_id": first_named("signal_id", row),
        "source_run_id": first_named("source_run_id", row),
        "agent_run_id": str(contract.get("agent_run_id") or "").strip() if status == "verified" and contract else None,
        "cycle_id": str(contract.get("cycle_id") or "").strip() if status == "verified" and contract else first_named(
            "cycle_id",
            row,
            features,
        ),
        "recommendation_id": first_named("recommendation_id", row, features, decision_lineage, snapshot, execution),
        "plan_id": first_named("plan_id", row, features, decision_lineage, execution),
        "broker_order_id": first_named("broker_order_id", row, features, decision_lineage, execution_quality, execution),
    }


def _hypothesis_lineage(
    rows: list[dict[str, Any]],
    *,
    collection: dict[str, Any] | None,
) -> dict[str, Any]:
    values: dict[str, set[str]] = {
        "signal_ids": set(),
        "source_run_ids": set(),
        "agent_run_ids": set(),
        "cycle_ids": set(),
        "recommendation_ids": set(),
        "plan_ids": set(),
        "broker_order_ids": set(),
    }
    field_names = {
        "signal_id": "signal_ids",
        "source_run_id": "source_run_ids",
        "agent_run_id": "agent_run_ids",
        "cycle_id": "cycle_ids",
        "recommendation_id": "recommendation_ids",
        "plan_id": "plan_ids",
        "broker_order_id": "broker_order_ids",
    }
    for row in rows:
        for field, value in _lineage_for_row(row).items():
            plural = field_names.get(field)
            if value and plural:
                values[plural].add(value)
    incoming = collection if isinstance(collection, dict) else {}
    window = incoming.get("window") if isinstance(incoming.get("window"), dict) else None
    as_of = str(incoming.get("as_of") or incoming.get("collected_at") or "").strip() or None
    return {
        **{field: sorted(items)[:20] or None for field, items in values.items()},
        "as_of": as_of,
        "window": dict(window) if window is not None else None,
    }


def _stage_feedback(
    rows: list[dict[str, Any]],
    *,
    collection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = Counter()
    decisions = Counter()
    gates = Counter()
    execution_statuses = Counter()
    selection_unavailable_ids: list[str] = []
    decision_unavailable_ids: list[str] = []
    execution_unverified_ids: list[str] = []
    execution_verified_ids: list[str] = []
    blocked_entry_ids: list[str] = []
    blocked_backtest_ids: list[str] = []
    legacy_unverified_ids: list[str] = []
    hypothesis_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        selected = features.get("selected_for_llm")
        selection["selected" if selected is True else "not_selected" if selected is False else "unavailable"] += 1
        if type(selected) is not bool:
            selection_unavailable_ids.append(str(row.get("signal_id") or ""))
            hypothesis_rows["selection_identity_unavailable"].append(row)
        decision = str(row.get("decision") or "unavailable")
        decisions[decision] += 1
        if _is_legacy_unverified(row):
            gates["legacy_unverified"] += 1
            legacy_unverified_ids.append(str(row.get("signal_id") or ""))
            hypothesis_rows["legacy_unverified"].append(row)
        _contract, attribution_status, _role = _agent_contract_from_signal(row)
        if decision not in {"candidate", "unavailable"} and attribution_status != "verified":
            decision_unavailable_ids.append(str(row.get("signal_id") or ""))
            hypothesis_rows["decision_identity_unavailable"].append(row)
        gate = row.get("gate") if isinstance(row.get("gate"), dict) else {}
        if any(bool(value) for value in gate.values()):
            gates["observed"] += 1
        if decision == "blocked_entry_quality":
            gates["blocked_entry_quality"] += 1
            blocked_entry_ids.append(str(row.get("signal_id") or ""))
            hypothesis_rows["blocked_entry_quality"].append(row)
        if decision == "blocked_backtest":
            gates["blocked_backtest"] += 1
            blocked_backtest_ids.append(str(row.get("signal_id") or ""))
            hypothesis_rows["blocked_backtest"].append(row)
        execution = _execution_payload(row)
        if execution:
            execution_statuses[str(execution.get("status") or "unavailable")] += 1
        if _execution_is_verified(row):
            gates["execution_verified"] += 1
            execution_verified_ids.append(str(row.get("signal_id") or ""))
        elif selected is True and decision in {"approved_buy", "approved_buy_micro", "approved_buy_soft_backtest", "executed_buy"}:
            execution_unverified_ids.append(str(row.get("signal_id") or ""))
            hypothesis_rows["execution_link_unverified"].append(row)

    hypotheses: list[dict[str, Any]] = []
    for stage, reason, ids, count in (
        ("selection", "selection_identity_unavailable", selection_unavailable_ids, selection["unavailable"]),
        ("decision", "decision_identity_unavailable", decision_unavailable_ids, len(decision_unavailable_ids)),
        ("gate", "blocked_entry_quality", blocked_entry_ids, gates["blocked_entry_quality"]),
        ("gate", "blocked_backtest", blocked_backtest_ids, gates["blocked_backtest"]),
        ("identity", "legacy_unverified", legacy_unverified_ids, gates["legacy_unverified"]),
        ("execution", "execution_link_unverified", execution_unverified_ids, len(execution_unverified_ids)),
    ):
        if count:
            hypotheses.append(
                {
                    "hypothesis_id": f"p-l104.{stage}.{reason}",
                    "legacy_hypothesis_id": f"p-l102.{stage}.{reason}",
                    "stage": stage,
                    "reason_code": reason,
                    "count": count,
                    "signal_ids": sorted({item for item in ids if item})[:20],
                    "lineage": _hypothesis_lineage(hypothesis_rows.get(reason, []), collection=collection),
                    "status": "observational",
                    "requires": "matured_outcome_and_same_cycle_control",
                }
            )
    return {
        "selection": {
            "selected": selection["selected"],
            "not_selected": selection["not_selected"],
            "unavailable": selection["unavailable"],
        },
        "decision": {"by_decision": dict(sorted(decisions.items()))},
        "gate": dict(sorted(gates.items())),
        "execution": {
            "by_status": dict(sorted(execution_statuses.items())),
            "verified_signal_ids": sorted({item for item in execution_verified_ids if item})[:20],
            "unverified_signal_ids": sorted({item for item in execution_unverified_ids if item})[:20],
        },
        "hypotheses": hypotheses,
    }


def _merge_stage_feedback(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge disjoint per-agent stage packets without restoring global counts."""

    merged: dict[str, Any] = {
        "selection": {"selected": 0, "not_selected": 0, "unavailable": 0},
        "decision": {"by_decision": {}},
        "gate": {},
        "execution": {"by_status": {}, "verified_signal_ids": [], "unverified_signal_ids": []},
        "hypotheses": [],
    }
    hypothesis_by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        selection = item.get("selection") if isinstance(item.get("selection"), dict) else {}
        for key in merged["selection"]:
            merged["selection"][key] += int(selection.get(key) or 0)
        decisions = (
            (item.get("decision") or {}).get("by_decision") or {}
            if isinstance(item.get("decision"), dict)
            else {}
        )
        for key, value in decisions.items():
            merged["decision"]["by_decision"][key] = merged["decision"]["by_decision"].get(key, 0) + int(value or 0)
        gates = item.get("gate") if isinstance(item.get("gate"), dict) else {}
        for key, value in gates.items():
            merged["gate"][key] = merged["gate"].get(key, 0) + int(value or 0)
        execution = item.get("execution") if isinstance(item.get("execution"), dict) else {}
        for key, value in (execution.get("by_status") or {}).items():
            merged["execution"]["by_status"][key] = merged["execution"]["by_status"].get(key, 0) + int(value or 0)
        for key in ("verified_signal_ids", "unverified_signal_ids"):
            merged["execution"][key].extend(execution.get(key) or [])
        for hypothesis in item.get("hypotheses") or []:
            if not isinstance(hypothesis, dict):
                continue
            hypothesis_id = str(hypothesis.get("hypothesis_id") or "").strip()
            if not hypothesis_id:
                continue
            existing = hypothesis_by_id.get(hypothesis_id)
            if existing is None:
                existing = dict(hypothesis)
                existing["signal_ids"] = list(hypothesis.get("signal_ids") or [])
                hypothesis_by_id[hypothesis_id] = existing
                continue
            existing["count"] = int(existing.get("count") or 0) + int(hypothesis.get("count") or 0)
            existing["signal_ids"] = sorted(set(existing["signal_ids"]) | set(hypothesis.get("signal_ids") or []))[:20]
            left_lineage = existing.get("lineage") if isinstance(existing.get("lineage"), dict) else {}
            right_lineage = hypothesis.get("lineage") if isinstance(hypothesis.get("lineage"), dict) else {}
            if left_lineage or right_lineage:
                merged_lineage: dict[str, Any] = {}
                for key in (
                    "signal_ids",
                    "source_run_ids",
                    "agent_run_ids",
                    "cycle_ids",
                    "recommendation_ids",
                    "plan_ids",
                    "broker_order_ids",
                ):
                    values = set(left_lineage.get(key) or []) | set(right_lineage.get(key) or [])
                    merged_lineage[key] = sorted(values)[:20] or None
                merged_lineage["as_of"] = (
                    left_lineage.get("as_of")
                    if left_lineage.get("as_of") == right_lineage.get("as_of")
                    else None
                )
                merged_lineage["window"] = (
                    left_lineage.get("window")
                    if left_lineage.get("window") == right_lineage.get("window")
                    else None
                )
                existing["lineage"] = merged_lineage
    merged["execution"]["verified_signal_ids"] = sorted(set(merged["execution"]["verified_signal_ids"]))[:20]
    merged["execution"]["unverified_signal_ids"] = sorted(set(merged["execution"]["unverified_signal_ids"]))[:20]
    merged["hypotheses"] = [hypothesis_by_id[key] for key in sorted(hypothesis_by_id)]
    merged["decision"]["by_decision"] = dict(sorted(merged["decision"]["by_decision"].items()))
    merged["gate"] = dict(sorted(merged["gate"].items()))
    merged["execution"]["by_status"] = dict(sorted(merged["execution"]["by_status"].items()))
    return merged


def _collection_metadata(
    rows: list[dict[str, Any]],
    collection: dict[str, Any] | None,
) -> dict[str, Any]:
    incoming = collection if isinstance(collection, dict) else {}
    returned = incoming.get("returned_rows")
    returned_rows = int(returned) if type(returned) is int and returned >= 0 else len(rows)
    limit = incoming.get("limit")
    limit_value = int(limit) if type(limit) is int and limit > 0 else None
    limit_reached = incoming.get("limit_reached")
    if not isinstance(limit_reached, bool):
        limit_reached = bool(limit_value and returned_rows >= limit_value)
    total_rows = incoming.get("total_rows")
    if type(total_rows) is not int or total_rows < returned_rows:
        total_rows = None
    window = incoming.get("window")
    if not isinstance(window, dict):
        window = None
    as_of = str(incoming.get("as_of") or incoming.get("collected_at") or "").strip() or None
    return {
        "returned_rows": returned_rows,
        "total_rows": total_rows,
        "limit": limit_value,
        "limit_reached": limit_reached,
        "completeness": (
            "partial_or_limit_reached"
            if limit_reached
            else str(incoming.get("completeness") or "unknown")
        ),
        "window": dict(window) if window is not None else None,
        "as_of": as_of,
    }


def _agent_horizon_stat(items: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    horizon_key = f"{horizon}d"
    matured = immature = maturity_unavailable = return_unavailable = direction_unavailable = 0
    excluded_trade_memory = 0
    values: list[float] = []
    net_values: list[float] = []
    gross_hits = net_hits = 0
    directions = Counter()
    for item in items:
        outcome = item.get("outcome") if isinstance(item.get("outcome"), dict) else {}
        matured_horizons = outcome.get("matured_horizons")
        flag = matured_horizons.get(horizon_key) if isinstance(matured_horizons, dict) else None
        if flag is True:
            matured += 1
            value, reason = _mature_signed_return_with_reason(item, outcome, horizon)
            if reason == "trade_memory":
                excluded_trade_memory += 1
            elif reason == "return_unavailable":
                return_unavailable += 1
            elif value is None:
                direction_unavailable += 1
            else:
                metric = _learning_metric_record(value)
                values.append(value)
                net_values.append(float(metric["net_return_10bps"]))
                gross_hits += int(metric["gross_gt_1pct"])
                net_hits += int(metric["hit_rate_net_10bps"])
                direction = _learning_direction(item)
                if direction:
                    directions[direction] += 1
        elif flag is False:
            immature += 1
        else:
            maturity_unavailable += 1
    evaluated = len(values)
    gross_average = sum(values) / evaluated if evaluated else None
    net_average = sum(net_values) / evaluated if evaluated else None
    net_hit_rate = net_hits / evaluated if evaluated else None
    return {
        "matured": matured,
        "immature": immature,
        "maturity_unavailable": maturity_unavailable,
        "return_unavailable": return_unavailable,
        "direction_unavailable": direction_unavailable,
        "excluded_trade_memory": excluded_trade_memory,
        "eligible_direction_corrected": evaluated,
        "evaluated": evaluated,
        "hits": net_hits,
        "hit_rate": round(net_hit_rate, 4) if net_hit_rate is not None else None,
        "hit_rate_net_10bps": round(net_hit_rate, 4) if net_hit_rate is not None else None,
        "signed_gross_return": round(gross_average, 4) if gross_average is not None else None,
        "net_return_10bps": round(net_average, 4) if net_average is not None else None,
        "gross_gt_1pct": {
            "hits": gross_hits,
            "rate": round(gross_hits / evaluated, 4) if evaluated else None,
        },
        "avg_return": round(gross_average, 4) if gross_average is not None else None,
        "directions": dict(sorted(directions.items())),
    }


def build_agent_learning_scoreboard(
    signals: list[dict[str, Any]] | None,
    *,
    collection: dict[str, Any] | None = None,
    independent_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize mature outcomes by the exact prospective agent contract.

    This is descriptive telemetry only. Missing or conflicting carriers stay
    outside every agent denominator, and explicit maturity is required before
    a return can contribute to hit-rate.
    """

    rows = list(signals or [])
    by_agent: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    unavailable_attribution = conflicting_attribution = 0
    producer_attributed = decision_attributed = 0
    fallback_count = llm_count = deterministic_count = 0
    execution_kind_counts = Counter()
    provider_values: list[str | None] = []
    model_values: list[str | None] = []
    fallback_reasons = Counter()
    parent_run_values: list[str | None] = []
    retry_of_values: list[str | None] = []
    selected = not_selected = selection_unavailable = 0
    gate_observed = execution_verified = 0
    legacy_unverified = 0
    matured = matured_with_control = attributed_matured = attributed_matured_with_control = 0
    for signal in rows:
        contract, status, role = _agent_contract_from_signal(signal)
        is_legacy_unverified = _is_legacy_unverified(signal)
        if is_legacy_unverified:
            legacy_unverified += 1
        features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
        selection = features.get("selected_for_llm")
        if selection is True:
            selected += 1
        elif selection is False:
            not_selected += 1
        else:
            selection_unavailable += 1
        gate = signal.get("gate") if isinstance(signal.get("gate"), dict) else {}
        if any(bool(value) for value in gate.values()):
            gate_observed += 1
        if _execution_is_verified(signal):
            execution_verified += 1
        if isinstance(signal.get("outcome"), dict) and (signal["outcome"].get("matured_horizons") or {}).get("10d") is True:
            matured += 1
            if status == "verified" and contract is not None and _control_is_same_cycle_verified(signal, contract):
                matured_with_control += 1
        if is_legacy_unverified:
            continue
        if status == "conflict":
            conflicting_attribution += 1
        elif status != "verified" or contract is None:
            unavailable_attribution += 1
        else:
            profile = _execution_profile(contract, role)
            execution_kind_counts[profile["kind"]] += 1
            provider_values.append(profile["provider"])
            model_values.append(profile["model"])
            parent_run_values.append(contract.get("parent_run_id"))
            retry_of_values.append(contract.get("retry_of"))
            if profile["kind"] == "fallback":
                fallback_count += 1
                if profile["fallback_reason"]:
                    fallback_reasons[profile["fallback_reason"]] += 1
            elif profile["kind"] == "llm":
                llm_count += 1
            elif profile["kind"] == "deterministic":
                deterministic_count += 1
            if isinstance(signal.get("outcome"), dict) and (signal["outcome"].get("matured_horizons") or {}).get("10d") is True:
                attributed_matured += 1
                if _control_is_same_cycle_verified(signal, contract):
                    attributed_matured_with_control += 1
            if role == "producer":
                agent_name = str(contract["canonical_agent_id"]).strip()
                producer_attributed += 1
            else:
                agent_name = str(contract["agent_name"]).strip()
                decision_attributed += 1
            by_agent[(role, agent_name)].append((signal, contract, profile))

    collection_info = _collection_metadata(rows, collection)
    stage_feedback = _stage_feedback(rows, collection=collection_info)

    agents: list[dict[str, Any]] = []
    for role, agent_name in sorted(by_agent):
        entries = by_agent[(role, agent_name)]
        agent_rows = [row for row, _contract, _profile in entries]
        contracts = [contract for _row, contract, _profile in entries]
        profiles = [profile for _row, _contract, profile in entries]
        decisions = Counter(str(row.get("decision") or "unknown") for row in agent_rows)
        decision_sources = Counter(str(contract.get("decision_source") or "unknown") for contract in contracts)
        agent_matured = sum(
            1
            for row, contract, _profile in entries
            if isinstance(row.get("outcome"), dict)
            and (row["outcome"].get("matured_horizons") or {}).get("10d") is True
        )
        agent_matured_with_control = sum(
            1
            for row, contract, _profile in entries
            if isinstance(row.get("outcome"), dict)
            and (row["outcome"].get("matured_horizons") or {}).get("10d") is True
            and _control_is_same_cycle_verified(row, contract)
        )
        agent_selection = Counter()
        agent_execution_verified = 0
        for row in agent_rows:
            features = row.get("features") if isinstance(row.get("features"), dict) else {}
            selected_value = features.get("selected_for_llm")
            agent_selection[
                "selected"
                if selected_value is True
                else "not_selected"
                if selected_value is False
                else "unavailable"
            ] += 1
            if _execution_is_verified(row):
                agent_execution_verified += 1
        execution_statuses = Counter()
        for row in agent_rows:
            gate = row.get("gate") if isinstance(row.get("gate"), dict) else {}
            execution = gate.get("execution") if isinstance(gate.get("execution"), dict) else {}
            execution_statuses[str(execution.get("status") or "unavailable")] += 1
        control_sets = sum(
            1
            for row, contract, _profile in entries
            if _control_is_same_cycle_verified(row, contract)
        )
        gate_observed_for_agent = sum(
            1
            for row in agent_rows
            if isinstance(row.get("gate"), dict)
            and any(bool(value) for value in row["gate"].values())
        )
        agents.append(
            {
                "agent_name": agent_name,
                "agent_role": role,
                "metric_scope": "attributed_agent",
                "agent_run_ids": sorted({str(contract["agent_run_id"]) for contract in contracts}),
                "cycles": sorted({str(contract["cycle_id"]) for contract in contracts}),
                "signal_ids": sorted({str(row.get("signal_id")) for row in agent_rows if str(row.get("signal_id") or "").strip()})[:160],
                "signals": len(agent_rows),
                "decisions": dict(sorted(decisions.items())),
                "decision_sources": dict(sorted(decision_sources.items())),
                "execution_kinds": dict(sorted(Counter(profile["kind"] for profile in profiles).items())),
                "providers": _counter_values([profile["provider"] for profile in profiles]),
                "models": _counter_values([profile["model"] for profile in profiles]),
                "parent_run_ids": _counter_values([contract.get("parent_run_id") for contract in contracts]),
                "retry_of": _counter_values([contract.get("retry_of") for contract in contracts]),
                "fallback_reasons": dict(
                    sorted(
                        Counter(
                            profile["fallback_reason"]
                            for profile in profiles
                            if profile["kind"] == "fallback" and profile["fallback_reason"]
                        ).items()
                    )
                ),
                "matured": agent_matured,
                "matured_with_control": agent_matured_with_control,
                "attributed_matured": agent_matured,
                "attributed_matured_with_control": agent_matured_with_control,
                "selected": agent_selection["selected"],
                "not_selected": agent_selection["not_selected"],
                "selection_unavailable": agent_selection["unavailable"],
                "gate": gate_observed_for_agent,
                "execution_verified": agent_execution_verified,
                "execution_statuses": dict(sorted(execution_statuses.items())),
                "comparable_control_sets": {
                    "verified": control_sets,
                    "total": len(agent_rows),
                    "coverage": round(control_sets / len(agent_rows), 4) if agent_rows else None,
                },
                "lineage": _hypothesis_lineage(agent_rows, collection=collection_info),
                "stage_feedback": _stage_feedback(agent_rows, collection=collection_info),
                "horizons": {
                    f"{horizon}d": _agent_horizon_stat(agent_rows, horizon)
                    for horizon in HORIZONS
                },
            }
        )

    attributed = sum(len(items) for items in by_agent.values())
    any_evaluated = any(
        agent["horizons"][f"{horizon}d"]["evaluated"]
        for agent in agents
        for horizon in HORIZONS
    )
    if not rows or not attributed:
        status = "unavailable"
    elif not any_evaluated:
        status = "collecting"
    elif unavailable_attribution or conflicting_attribution:
        status = "partial"
    else:
        status = "available"
    maturity = _feedback_maturity(agents)
    same_cycle_control = _feedback_control(
        maturity,
        {"attributed_matured_with_control": attributed_matured_with_control},
    )
    measurement_status = _measurement_status(
        agent_slice=agents,
        maturity=maturity,
        control=same_cycle_control,
        collection=collection_info,
    )
    actionability_blockers: list[str] = []
    if collection_info.get("limit_reached") is True:
        actionability_blockers.append("collection_limit_reached")
    if not any_evaluated:
        actionability_blockers.append("no_direction_corrected_mature_returns")
    if attributed_matured_with_control == 0:
        actionability_blockers.append("no_same_cycle_control_verified_at_10d")
    actionability_blockers.append("quality_status_not_evaluable")
    actionability_blockers = [item for item in actionability_blockers if item]
    return {
        "schema_version": AGENT_LEARNING_SCHEMA_VERSION,
        "metric_scope": "attributed_agent",
        "signal_metrics": {
            "sample_unit": "signal",
            "source": "attributed_agent_outcomes",
        },
        "portfolio_metrics": _portfolio_metrics_unavailable(),
        "status": status,
        "quality_status": "not_evaluable",
        "quality_reason": "same_cycle_control_and_promotion_not_established",
        "independent_validation": (
            dict(independent_validation)
            if isinstance(independent_validation, dict)
            else None
        ),
        "measurement_status": measurement_status,
        "maturity": maturity,
        "same_cycle_control": same_cycle_control,
        "collection": collection_info,
        "denominators": {
            "signals_total": len(rows),
            "attributed": attributed,
            "producer_attributed": producer_attributed,
            "decision_attributed": decision_attributed,
            "unavailable_attribution": unavailable_attribution,
            "conflicting_attribution": conflicting_attribution,
            "attribution_coverage": round(attributed / len(rows), 4) if rows else None,
            "fallback": fallback_count,
            "llm": llm_count,
            "deterministic": deterministic_count,
            "execution_kinds": dict(sorted(execution_kind_counts.items())),
            "providers": _counter_values(provider_values),
            "models": _counter_values(model_values),
            "fallback_reasons": dict(sorted(fallback_reasons.items())),
            "parent_run_ids": _counter_values(parent_run_values),
            "retry_of": _counter_values(retry_of_values),
            "selected": selected,
            "not_selected": not_selected,
            "selection_unavailable": selection_unavailable,
            "gate": gate_observed,
            "execution_verified": execution_verified,
            "legacy_unverified": legacy_unverified,
            "matured": matured,
            "attributed_matured": attributed_matured,
            "matured_with_control": matured_with_control,
            "attributed_matured_with_control": attributed_matured_with_control,
        },
        "agents": agents,
        "stage_feedback": stage_feedback,
        "actionability": {
            "status": "blocked" if actionability_blockers else "ready_for_review",
            "descriptive_metrics_available": any_evaluated,
            "usable_for_agent_learning": False,
            "usable_for_promotion": False,
            "blockers": actionability_blockers,
        },
        "method": {
            "identity": (
                "producer_agent_contract preferred; decision agent_contract only when producer identity "
                "is unavailable; never infer from symbol/source"
            ),
            "hit_definition": (
                "hit_rate_net_10bps uses signed forward return minus 10 bps > 0; "
                "gross_gt_1pct is retained as a separate historical metric; "
                "short reverses raw return; exit requires explicit position_direction"
            ),
            "metric_aliases": {
                "hit_rate": "hit_rate_net_10bps",
                "avg_return": "signed_gross_return",
            },
            "eligible_denominator": (
                "explicit mature outcome + return available + valid direction + "
                "source is not trade_memory"
            ),
            "missing_identity": "excluded_from_agent_denominators",
            "missing_direction": "excluded_from_direction_corrected_hit_denominators",
            "same_cycle_control": "10d mature signal and verified control with matching signal_id and cycle_id",
            "fallback": "separate from llm/deterministic; provider, model and reason retained when available",
            "promotion": "disabled_until_mature_outcomes_and_same_cycle_controls",
        },
    }


def _scoped_agent_denominators(agent_slice: list[dict[str, Any]]) -> dict[str, Any]:
    """Build denominators from only the selected agent rows."""

    def total(key: str) -> int:
        return sum(
            int(item.get(key) or 0)
            for item in agent_slice
            if type(item.get(key) or 0) is int and int(item.get(key) or 0) >= 0
        )

    def merge_counter(key: str) -> dict[str, int]:
        merged: Counter[str] = Counter()
        for item in agent_slice:
            values = item.get(key) if isinstance(item.get(key), dict) else {}
            for name, value in values.items():
                if type(value) is int and value >= 0:
                    merged[str(name)] += value
        return dict(sorted(merged.items()))

    def total_horizon(key: str) -> int:
        result = 0
        for item in agent_slice:
            horizon = ((item.get("horizons") or {}).get("10d") or {})
            value = horizon.get(key) if isinstance(horizon, dict) else None
            if type(value) is int and value >= 0:
                result += value
        return result

    signals = total("signals")
    execution_kinds = merge_counter("execution_kinds")
    return {
        "signals_total": signals,
        "attributed": signals,
        "producer_attributed": sum(
            item.get("signals", 0)
            for item in agent_slice
            if item.get("agent_role") == "producer" and type(item.get("signals", 0)) is int
        ),
        "decision_attributed": sum(
            item.get("signals", 0)
            for item in agent_slice
            if item.get("agent_role") == "decision" and type(item.get("signals", 0)) is int
        ),
        "unavailable_attribution": 0,
        "conflicting_attribution": 0,
        "attribution_coverage": 1.0 if signals else None,
        "fallback": execution_kinds.get("fallback", 0),
        "llm": execution_kinds.get("llm", 0),
        "deterministic": execution_kinds.get("deterministic", 0),
        "execution_kinds": execution_kinds,
        "providers": merge_counter("providers"),
        "models": merge_counter("models"),
        "fallback_reasons": merge_counter("fallback_reasons"),
        "parent_run_ids": merge_counter("parent_run_ids"),
        "retry_of": merge_counter("retry_of"),
        "selected": total("selected"),
        "not_selected": total("not_selected"),
        "selection_unavailable": total("selection_unavailable"),
        "gate": total("gate"),
        "execution_verified": total("execution_verified"),
        "legacy_unverified": None,
        "matured": total("matured"),
        "attributed_matured": total("attributed_matured"),
        "matured_with_control": total("matured_with_control"),
        "attributed_matured_with_control": total("attributed_matured_with_control"),
        "immature": total_horizon("immature"),
        "maturity_unavailable": total_horizon("maturity_unavailable"),
        "return_unavailable": total_horizon("return_unavailable"),
        "direction_unavailable": total_horizon("direction_unavailable"),
        "excluded_trade_memory": total_horizon("excluded_trade_memory"),
    }


def _feedback_maturity(agent_slice: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize only explicit 10d maturity fields from one agent slice."""

    def count(value: Any) -> int:
        return value if type(value) is int and value >= 0 else 0

    totals = {
        "matured": 0,
        "evaluated": 0,
        "immature": 0,
        "maturity_unavailable": 0,
        "return_unavailable": 0,
        "direction_unavailable": 0,
    }
    for agent in agent_slice:
        horizon = (agent.get("horizons") or {}).get("10d", {})
        if not isinstance(horizon, dict):
            continue
        for key in totals:
            totals[key] += count(horizon.get(key))
    if not agent_slice:
        status = "unavailable"
    elif totals["matured"] == 0:
        status = "immature" if totals["immature"] else "unavailable"
    elif totals["evaluated"] < totals["matured"]:
        status = "partial"
    else:
        status = "matured"
    return {"horizon": "10d", "status": status, **totals}


def _feedback_control(
    maturity: dict[str, Any],
    denominators: dict[str, Any],
) -> dict[str, Any]:
    matured = maturity.get("matured", 0)
    verified = denominators.get("attributed_matured_with_control", 0)
    if type(matured) is not int or matured < 0 or type(verified) is not int or verified < 0:
        return {"horizon": "10d", "status": "unavailable", "matured": None, "verified": None, "coverage": None}
    if matured == 0:
        status = "unavailable"
    elif verified == 0:
        status = "not_comparable"
    elif verified < matured:
        status = "partial"
    else:
        status = "verified"
    return {
        "horizon": "10d",
        "status": status,
        "matured": matured,
        "verified": verified,
        "coverage": round(verified / matured, 4) if matured else None,
    }


def _measurement_status(
    *,
    agent_slice: list[dict[str, Any]],
    maturity: dict[str, Any],
    control: dict[str, Any],
    collection: dict[str, Any],
) -> str:
    if not agent_slice:
        return "unavailable"
    if collection.get("limit_reached") is True:
        return "collection_truncated"
    if collection.get("limit_reached") is not False:
        return "collection_unavailable"
    if maturity.get("matured", 0) == 0 or maturity.get("evaluated", 0) < maturity.get("matured", 0):
        return "not_evaluable"
    if control.get("status") != "verified":
        return "not_comparable"
    return "ready_for_shadow_review"


def _validation_hash(value: Mapping[str, Any]) -> str | None:
    try:
        payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validation_subject(
    *,
    canonical: str | None,
    agent_slice: list[dict[str, Any]],
    source_collection: dict[str, Any],
    maturity: dict[str, Any],
    control: dict[str, Any],
) -> dict[str, Any]:
    agent_run_ids = sorted(
        {
            str(value).strip()
            for agent in agent_slice
            for value in (agent.get("agent_run_ids") or [])
            if str(value).strip()
        }
    )
    signal_ids = sorted(
        {
            str(value).strip()
            for agent in agent_slice
            for value in (agent.get("signal_ids") or [])
            if str(value).strip()
        }
    )
    collection = {
        key: source_collection.get(key)
        for key in ("returned_rows", "total_rows", "limit", "limit_reached", "completeness", "window", "as_of")
    }
    return {
        "canonical_agent_id": canonical,
        "agent_run_ids": agent_run_ids,
        "signal_ids": signal_ids,
        "source_collection": collection,
        "maturity": {
            "horizon": maturity.get("horizon"),
            "matured": maturity.get("matured"),
            "evaluated": maturity.get("evaluated"),
        },
        "control": {
            "horizon": control.get("horizon"),
            "status": control.get("status"),
            "matured": control.get("matured"),
            "verified": control.get("verified"),
            "coverage": control.get("coverage"),
        },
    }


def _feedback_window_is_valid(collection: Mapping[str, Any]) -> bool:
    window = collection.get("window")
    if not isinstance(window, Mapping):
        return True
    values: dict[str, datetime] = {}
    for field in ("start", "end"):
        value = str(window.get(field) or "").strip()
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return False
        values[field] = parsed.astimezone(timezone.utc)
    as_of_text = str(collection.get("as_of") or "").strip()
    as_of = None
    if as_of_text:
        try:
            as_of = datetime.fromisoformat(as_of_text.replace("Z", "+00:00"))
        except ValueError:
            return False
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            return False
        as_of = as_of.astimezone(timezone.utc)
    return values["start"] < values["end"] and (as_of is None or values["end"] <= as_of)


def _canonical_agent_validation_resolution(
    resolved: Any,
    *,
    validation: Mapping[str, Any],
    subject: Mapping[str, Any],
) -> tuple[bool, str]:
    """Check the response from the trusted canonical evidence reader."""

    if not isinstance(resolved, Mapping) or resolved.get("status") != "verified":
        return False, "independent_validation_provenance_unresolved"
    if (
        resolved.get("artifact_id") != validation.get("artifact_id")
        or resolved.get("artifact_hash") != validation.get("artifact_hash")
        or resolved.get("subject_hash") != validation.get("subject_hash")
        or resolved.get("canonical_agent_id") != subject.get("canonical_agent_id")
        or resolved.get("agent_run_ids") != subject.get("agent_run_ids")
        or resolved.get("signal_ids") != subject.get("signal_ids")
        or resolved.get("source_collection") != subject.get("source_collection")
        or resolved.get("maturity") != subject.get("maturity")
        or resolved.get("control") != subject.get("control")
        or resolved.get("validation_run_id") != validation.get("validation_run_id")
        or resolved.get("validator_id") != validation.get("validator_id")
        or resolved.get("independent") is not True
    ):
        return False, "independent_validation_canonical_mismatch"
    refs = resolved.get("source_refs")
    adapters = resolved.get("source_adapters")
    if (
        not isinstance(refs, list)
        or not refs
        or any(not str(value).strip() for value in refs)
        or refs != validation.get("evidence_refs")
        or not isinstance(adapters, Mapping)
        or adapters != validation.get("source_adapters")
    ):
        return False, "independent_validation_canonical_evidence_missing"
    return True, "independent_validation_verified"


def _validation_metadata_for_scope(
    report: dict[str, Any],
    *,
    target: str | None,
    canonical: str | None,
    agent_slice: list[dict[str, Any]],
    source_collection: dict[str, Any],
    maturity: dict[str, Any],
    control: dict[str, Any],
    canonical_validation_resolver: CanonicalValidationResolver | None = None,
) -> dict[str, Any]:
    """Check artifact integrity, then require canonical evidence resolution."""

    candidates: list[Any] = []
    by_agent = report.get("independent_validation_by_agent")
    if isinstance(by_agent, dict):
        for key in (canonical, target):
            if key and isinstance(by_agent.get(key), dict):
                candidates.append(by_agent[key])
    for key in ("independent_validation", "validation", "evidence_validation"):
        value = report.get(key)
        if isinstance(value, dict):
            if "schema_version" in value or "artifact_hash" in value:
                candidates.append(value)
            else:
                for name in (canonical, target):
                    if name and isinstance(value.get(name), dict):
                        candidates.append(value[name])
    validation = next((item for item in candidates if isinstance(item, dict)), {})
    blockers: list[str] = []
    if not validation:
        return {
            "status": "unavailable",
            "validation_run_id": None,
            "validator_id": None,
            "independent": False,
            "evidence_refs": [],
            "integrity_status": "missing",
            "passed": False,
            "blockers": ["independent_validation_required"],
        }
    allowed = {
        "schema_version",
        "artifact_id",
        "artifact_hash",
        "subject_hash",
        "status",
        "independent",
        "validation_run_id",
        "validator_id",
        "canonical_agent_id",
        "agent_run_ids",
        "signal_ids",
        "source_collection",
        "maturity",
        "control",
        "evidence_refs",
        "source_adapters",
        "verification_receipt",
    }
    if set(validation) - allowed:
        blockers.append("independent_validation_artifact_unknown_fields")
    supplied_hash = str(validation.get("artifact_hash") or "").strip()
    payload = {key: validation[key] for key in validation if key != "artifact_hash"}
    expected_hash = _validation_hash(payload)
    if not supplied_hash or supplied_hash != expected_hash:
        blockers.append("independent_validation_artifact_hash_invalid")
    if validation.get("schema_version") != AGENT_VALIDATION_ARTIFACT_SCHEMA_VERSION:
        blockers.append("independent_validation_artifact_schema_invalid")
    if not str(validation.get("artifact_id") or "").strip():
        blockers.append("independent_validation_artifact_id_required")
    status = str(validation.get("status") or "").strip().lower()
    independent = validation.get("independent") is True
    validation_run_id = str(validation.get("validation_run_id") or "").strip()
    validator_id = str(validation.get("validator_id") or "").strip()
    if status != "validated":
        blockers.append("independent_validation_not_passed")
    if not independent:
        blockers.append("independent_validation_not_independent")
    if not validation_run_id:
        blockers.append("independent_validation_run_id_required")
    if not validator_id:
        blockers.append("independent_validator_id_required")
    subject = _validation_subject(
        canonical=canonical,
        agent_slice=agent_slice,
        source_collection=source_collection,
        maturity=maturity,
        control=control,
    )
    if validation.get("subject_hash") != _validation_hash(subject):
        blockers.append("independent_validation_subject_hash_invalid")
    if validation.get("canonical_agent_id") != canonical:
        blockers.append("independent_validation_agent_mismatch")
    expected_agent_runs = subject["agent_run_ids"]
    expected_signal_ids = subject["signal_ids"]
    if validation.get("agent_run_ids") != expected_agent_runs:
        blockers.append("independent_validation_agent_lineage_mismatch")
    if validation.get("signal_ids") != expected_signal_ids:
        blockers.append("independent_validation_signal_lineage_mismatch")
    if validation.get("source_collection") != subject["source_collection"]:
        blockers.append("independent_validation_collection_mismatch")
    if validation.get("maturity") != subject["maturity"]:
        blockers.append("independent_validation_maturity_mismatch")
    if validation.get("control") != subject["control"]:
        blockers.append("independent_validation_control_mismatch")
    if not _feedback_window_is_valid(subject["source_collection"]):
        blockers.append("independent_validation_collection_window_invalid")
    if validation_run_id in set(expected_agent_runs):
        blockers.append("independent_validation_self_referential")
    refs = validation.get("evidence_refs")
    adapters = validation.get("source_adapters")
    if (
        not isinstance(refs, list)
        or not refs
        or any(not str(value).strip() for value in refs)
        or not isinstance(adapters, dict)
        or not all(str(adapters.get(name) or "").strip() for name in ("agent_events", "h_capture", "point_in_time_replay"))
    ):
        blockers.append("independent_validation_evidence_incomplete")
    receipt = validation.get("verification_receipt")
    expected_receipt = _validation_hash(
        {
            "subject_hash": validation.get("subject_hash"),
            "source_adapters": adapters,
            "validation_run_id": validation_run_id,
            "validator_id": validator_id,
        }
    )
    if not isinstance(receipt, dict) or receipt.get("status") != "verified" or receipt.get("hash") != expected_receipt:
        blockers.append("independent_validation_receipt_invalid")
    integrity_status = "invalid" if blockers else "valid_unverified"
    if not blockers:
        if canonical_validation_resolver is None:
            blockers.append("independent_validation_provenance_unresolved")
        else:
            try:
                resolved = canonical_validation_resolver(validation)
            except Exception:  # noqa: BLE001 - an unavailable verifier must fail closed.
                resolved = None
            verified, reason = _canonical_agent_validation_resolution(
                resolved,
                validation=validation,
                subject=subject,
            )
            if not verified:
                blockers.append(reason)
            else:
                integrity_status = "verified"
    return {
        "status": status or "unavailable",
        "validation_run_id": validation_run_id or None,
        "validator_id": validator_id or None,
        "independent": independent,
        "evidence_refs": list(refs) if isinstance(refs, list) else [],
        "artifact_id": str(validation.get("artifact_id") or "").strip() or None,
        "artifact_hash": supplied_hash or None,
        "integrity_status": integrity_status,
        "passed": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _feedback_conflicts(
    report: dict[str, Any],
    denominators: dict[str, Any],
) -> dict[str, int]:
    source = report.get("denominators") if isinstance(report.get("denominators"), dict) else {}

    def count(key: str) -> int:
        value = source.get(key, denominators.get(key))
        return value if type(value) is int and value >= 0 else 0

    return {
        "unavailable_attribution": count("unavailable_attribution"),
        "conflicting_attribution": count("conflicting_attribution"),
        "legacy_unverified": count("legacy_unverified"),
    }


def _feedback_exclusions(agent_slice: list[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "immature",
        "maturity_unavailable",
        "return_unavailable",
        "direction_unavailable",
        "excluded_trade_memory",
    )
    result = {key: 0 for key in keys}
    for agent in agent_slice:
        horizon = (agent.get("horizons") or {}).get("10d", {})
        if not isinstance(horizon, dict):
            continue
        for key in keys:
            value = horizon.get(key)
            if type(value) is int and value >= 0:
                result[key] += value
    return result


def _feedback_coverage(
    source_collection: dict[str, Any],
    denominators: dict[str, Any],
    agent_slice: list[dict[str, Any]],
) -> dict[str, Any]:
    source_returned = source_collection.get("returned_rows")
    source_total = source_collection.get("total_rows")
    source_coverage = (
        round(source_returned / source_total, 4)
        if type(source_returned) is int
        and source_returned >= 0
        and type(source_total) is int
        and source_total > 0
        else None
    )
    source_attribution = denominators.get("attribution_coverage")
    if not isinstance(source_attribution, (int, float)) or isinstance(source_attribution, bool):
        source_attribution = None
    source_attribution = round(float(source_attribution), 4) if source_attribution is not None else None
    slice_rows = denominators.get("signals_total")
    slice_share = (
        round(slice_rows / source_total, 4)
        if type(slice_rows) is int
        and slice_rows >= 0
        and type(source_total) is int
        and source_total > 0
        else None
    )
    return {
        "source_rows": source_returned if type(source_returned) is int else None,
        "source_total_rows": source_total if type(source_total) is int else None,
        "source_coverage": source_coverage,
        "source_attribution_coverage": source_attribution,
        "agent_slice_rows": slice_rows if type(slice_rows) is int else len(agent_slice),
        "agent_slice_share": slice_share,
        "same_cycle_control_coverage": None,
    }


def _deterministic_feedback_gates(
    report: dict[str, Any],
    *,
    source_collection: dict[str, Any],
    denominators: dict[str, Any],
    agent_slice: list[dict[str, Any]],
    maturity: dict[str, Any],
    control: dict[str, Any],
    target: str | None,
    canonical: str | None,
    canonical_validation_resolver: CanonicalValidationResolver | None = None,
) -> dict[str, Any]:
    conflicts = _feedback_conflicts(report, denominators)
    exclusions = _feedback_exclusions(agent_slice)
    coverage = _feedback_coverage(source_collection, denominators, agent_slice)
    validation = _validation_metadata_for_scope(
        report,
        target=target,
        canonical=canonical,
        agent_slice=agent_slice,
        source_collection=source_collection,
        maturity=maturity,
        control=control,
        canonical_validation_resolver=canonical_validation_resolver,
    )

    integrity_blockers: list[str] = []
    if str(report.get("status") or "").strip().lower() in {"unavailable", "partial"}:
        integrity_blockers.append("source_integrity_not_complete")
    if any(conflicts.values()):
        integrity_blockers.append("source_attribution_conflict_or_unavailable")
    source_attribution = coverage.get("source_attribution_coverage")
    if source_attribution != 1.0:
        integrity_blockers.append("source_attribution_incomplete")

    maturity_blockers: list[str] = []
    matured = maturity.get("matured")
    evaluated = maturity.get("evaluated")
    if type(matured) is not int or matured <= 0 or type(evaluated) is not int or evaluated <= 0:
        maturity_blockers.append("no_direction_corrected_mature_returns")
    if type(matured) is int and type(evaluated) is int and evaluated < matured:
        maturity_blockers.append("matured_outcome_denominator_incomplete")
    if any(exclusions[key] for key in ("immature", "maturity_unavailable")):
        maturity_blockers.append("maturity_pending_or_unavailable_at_10d")
    if any(exclusions[key] for key in ("return_unavailable", "direction_unavailable", "excluded_trade_memory")):
        maturity_blockers.append("mature_outcome_exclusions_present_at_10d")

    control_blockers: list[str] = []
    if control.get("status") != "verified":
        control_blockers.append("no_same_cycle_control_verified_at_10d")
    if (
        type(matured) is int
        and matured > 0
        and control.get("status") == "verified"
        and control.get("verified") != matured
    ):
        control_blockers.append("same_cycle_control_denominator_incomplete_at_10d")

    denominator_blockers: list[str] = []
    if source_collection.get("limit_reached") is True:
        denominator_blockers.append("collection_limit_reached")
    elif source_collection.get("limit_reached") is not False:
        denominator_blockers.append("source_collection_completeness_unavailable")
    if source_collection.get("completeness") not in {"complete", "full"}:
        denominator_blockers.append("source_collection_incomplete")
    source_returned = source_collection.get("returned_rows")
    source_total = source_collection.get("total_rows")
    if type(source_total) is not int or source_total < 0:
        denominator_blockers.append("source_total_rows_unavailable")
    elif type(source_returned) is not int or source_returned != source_total:
        denominator_blockers.append("source_row_count_mismatch")
    if coverage.get("source_attribution_coverage") != 1.0:
        denominator_blockers.append("attribution_denominator_incomplete")

    gates = {
        "integrity": {
            "passed": not integrity_blockers,
            "blockers": integrity_blockers,
            "conflicts": conflicts,
        },
        "maturity": {
            "passed": not maturity_blockers,
            "blockers": maturity_blockers,
            "horizon": "10d",
        },
        "same_cycle_control": {
            "passed": not control_blockers,
            "blockers": control_blockers,
            "horizon": "10d",
        },
        "independent_validation": {
            "passed": validation["passed"],
            "blockers": list(validation["blockers"]),
            "metadata": validation,
        },
        "denominators_complete": {
            "passed": not denominator_blockers,
            "blockers": denominator_blockers,
            "coverage": coverage,
        },
    }
    blockers: list[str] = []
    for gate in gates.values():
        for blocker in gate.get("blockers", []):
            if blocker not in blockers:
                blockers.append(blocker)
    return {
        "all_passed": all(bool(gate.get("passed")) for gate in gates.values()),
        "blockers": blockers,
        "gates": gates,
        "coverage": coverage,
        "conflicts": conflicts,
        "exclusions": exclusions,
        "independent_validation": validation,
    }


def _empty_lineage(*, collection: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_ids": None,
        "source_run_ids": None,
        "agent_run_ids": None,
        "cycle_ids": None,
        "recommendation_ids": None,
        "plan_ids": None,
        "broker_order_ids": None,
        "as_of": collection.get("as_of"),
        "window": collection.get("window"),
    }


def _slice_lineage(
    agent_slice: list[dict[str, Any]],
    *,
    collection: dict[str, Any],
) -> dict[str, Any]:
    fields = (
        "signal_ids",
        "source_run_ids",
        "agent_run_ids",
        "cycle_ids",
        "recommendation_ids",
        "plan_ids",
        "broker_order_ids",
    )
    values = {field: set() for field in fields}
    for item in agent_slice:
        lineage = item.get("lineage") if isinstance(item.get("lineage"), dict) else {}
        sources = lineage or {
            "signal_ids": item.get("signal_ids"),
            "agent_run_ids": item.get("agent_run_ids"),
            "cycle_ids": item.get("cycles"),
        }
        for field in fields:
            values[field].update(str(value).strip() for value in (sources.get(field) or []) if str(value).strip())
    lineage = _empty_lineage(collection=collection)
    for field, items in values.items():
        lineage[field] = sorted(items)[:160] or None
    return lineage


def build_structured_agent_evidence_packet(
    feedback: dict[str, Any] | None,
    *,
    reason_code: str,
    subject: str,
    summary: str,
    confidence: str,
    evidence: list[str],
) -> dict[str, Any]:
    """Build stable specialist evidence without adding decision authority."""

    scoped = feedback if isinstance(feedback, dict) else {}
    collection = scoped.get("collection") if isinstance(scoped.get("collection"), dict) else {}
    agent_slice = [item for item in scoped.get("agent_slice", []) if isinstance(item, dict)]
    denominators = scoped.get("denominators") if isinstance(scoped.get("denominators"), dict) else {}
    maturity = scoped.get("maturity") if isinstance(scoped.get("maturity"), dict) else _feedback_maturity(agent_slice)
    control = scoped.get("same_cycle_control") if isinstance(scoped.get("same_cycle_control"), dict) else _feedback_control(maturity, denominators)
    stage = scoped.get("stage_feedback") if isinstance(scoped.get("stage_feedback"), dict) else {}
    matches = [
        item
        for item in stage.get("hypotheses", [])
        if isinstance(item, dict) and item.get("reason_code") == reason_code
    ]
    stage_ids = [str(item.get("hypothesis_id") or "").strip() for item in matches]
    legacy_ids = []
    for item in matches:
        legacy_id = str(item.get("legacy_hypothesis_id") or "").strip()
        stage_id = str(item.get("hypothesis_id") or "").strip()
        if not legacy_id and stage_id.startswith("p-l102."):
            legacy_id = stage_id
        if legacy_id:
            legacy_ids.append(legacy_id)
    if len(matches) == 1 and isinstance(matches[0].get("lineage"), dict):
        lineage = dict(matches[0]["lineage"])
        evidence_status = "verified_carrier"
    elif len(matches) > 1:
        lineage = _empty_lineage(collection=collection)
        evidence_status = "ambiguous"
    else:
        lineage = _slice_lineage(agent_slice, collection=collection)
        evidence_status = "slice_carrier" if agent_slice else "unavailable"
    canonical = str(scoped.get("canonical_agent_id") or "").strip() or canonical_agent_id(scoped.get("agent_name"))
    agent_name = str(scoped.get("agent_name") or "").strip() or None
    agent_key = canonical or "unavailable"
    return {
        "schema_version": AGENT_EVIDENCE_PACKET_SCHEMA_VERSION,
        "hypothesis_id": f"p-l104.specialist.{agent_key}.{reason_code}",
        "reason_code": reason_code,
        "canonical_agent_id": canonical,
        "agent_name": agent_name,
        "lineage": lineage,
        "denominators": dict(denominators),
        "maturity": dict(maturity),
        "same_cycle_control": dict(control),
        "measurement_status": scoped.get("measurement_status", "unavailable"),
        "structured_evidence": {
            "status": evidence_status,
            "stage_hypothesis_ids": stage_ids or None,
            "legacy_hypothesis_ids": legacy_ids or None,
            "scope": scoped.get("scope", "unavailable"),
            "collection": {
                "returned_rows": collection.get("returned_rows"),
                "total_rows": collection.get("total_rows"),
                "limit": collection.get("limit"),
                "as_of": collection.get("as_of"),
                "window": collection.get("window"),
                "completeness": collection.get("completeness", "unavailable"),
                "limit_reached": collection.get("limit_reached"),
            },
        },
        # Keep legacy presentation fields while making structured fields authoritative.
        "subject": subject,
        "summary": summary,
        "confidence": confidence,
        "evidence": list(evidence),
    }


def build_agent_learning_feedback(
    scoreboard: dict[str, Any] | None,
    *,
    agent_name: str | None = None,
    canonical_validation_resolver: CanonicalValidationResolver | None = None,
) -> dict[str, Any]:
    """Expose a bounded, non-authoritative scoreboard slice to one specialist."""

    report = scoreboard if isinstance(scoreboard, dict) else build_agent_learning_scoreboard([])
    target = str(agent_name or "").strip()
    canonical = canonical_agent_id(target) if target else None
    wanted = {item for item in (target, canonical) if item}
    agent_slice = [
        item
        for item in list(report.get("agents") or [])
        if str(item.get("agent_name") or "").strip() in wanted
    ]
    scoped = bool(target)
    scoped_denominators = _scoped_agent_denominators(agent_slice) if scoped else dict(report.get("denominators") or {})
    source_collection = report.get("collection") if isinstance(report.get("collection"), dict) else {}
    if scoped:
        scoped_collection = {
            "returned_rows": scoped_denominators["signals_total"],
            "total_rows": None,
            "limit": source_collection.get("limit"),
            "limit_reached": source_collection.get("limit_reached"),
            "completeness": (
                "scoped_agent_slice_truncated"
                if source_collection.get("limit_reached") is True
                else "scoped_agent_slice"
            ),
            "source_completeness": source_collection.get("completeness", "unavailable"),
            "source_returned_rows": source_collection.get("returned_rows"),
            "source_total_rows": source_collection.get("total_rows"),
            "source_limit": source_collection.get("limit"),
            "source_limit_reached": source_collection.get("limit_reached"),
            "window": source_collection.get("window"),
            "as_of": source_collection.get("as_of"),
        }
        scoped_stage_feedback = _merge_stage_feedback(
            [
                item["stage_feedback"]
                for item in agent_slice
                if isinstance(item.get("stage_feedback"), dict)
            ]
        )
    else:
        scoped_collection = dict(report.get("collection") or {})
        scoped_stage_feedback = dict(report.get("stage_feedback") or {})
    maturity = _feedback_maturity(agent_slice) if scoped else dict(report.get("maturity") or {})
    same_cycle_control = (
        _feedback_control(maturity, scoped_denominators)
        if scoped
        else dict(report.get("same_cycle_control") or {})
    )
    measurement_status = (
        _measurement_status(
            agent_slice=agent_slice,
            maturity=maturity,
            control=same_cycle_control,
            collection=scoped_collection,
        )
        if scoped
        else report.get("measurement_status", "unavailable")
    )
    evaluation_agents = agent_slice if scoped else [
        item for item in list(report.get("agents") or []) if isinstance(item, dict)
    ]
    deterministic = _deterministic_feedback_gates(
        report,
        source_collection=source_collection,
        denominators=scoped_denominators,
        agent_slice=evaluation_agents,
        maturity=maturity,
        control=same_cycle_control,
        target=target if scoped else None,
        canonical=canonical,
        canonical_validation_resolver=canonical_validation_resolver,
    )
    coverage = dict(deterministic["coverage"])
    coverage["same_cycle_control_coverage"] = same_cycle_control.get("coverage")
    deterministic["coverage"] = coverage
    all_passed = bool(deterministic["all_passed"])
    collecting_blockers = {
        "collection_limit_reached",
        "source_collection_completeness_unavailable",
        "source_collection_incomplete",
        "source_total_rows_unavailable",
        "source_row_count_mismatch",
        "maturity_pending_or_unavailable_at_10d",
        "no_direction_corrected_mature_returns",
    }
    actionability_blockers = list(deterministic["blockers"])
    actionability = {
        "status": "ready_for_review"
        if all_passed
        else "collecting"
        if any(item in collecting_blockers for item in actionability_blockers)
        else "blocked",
        "descriptive_metrics_available": bool(maturity.get("evaluated")),
        "usable_for_agent_learning": all_passed,
        "usable_for_promotion": False,
        "blockers": actionability_blockers,
    }
    eligibility = {
        "status": "eligible_for_shadow_learning" if all_passed else actionability["status"],
        "eligible_for_agent_learning": all_passed,
        "promotion_eligible": False,
        "blockers": actionability_blockers,
        "method": "deterministic_gates_only",
    }
    return {
        "schema_version": AGENT_LEARNING_FEEDBACK_SCHEMA_VERSION,
        "scope": "agent_slice" if target else "global",
        "agent_name": target or None,
        "canonical_agent_id": canonical,
        "metric_scope": "signal",
        "signal_metrics": {
            "sample_unit": "signal",
            "source": "attributed_agent_outcomes",
        },
        "portfolio_metrics": _portfolio_metrics_unavailable(),
        "status": report.get("status", "unavailable"),
        "quality_status": report.get("quality_status", "not_evaluable"),
        "measurement_status": measurement_status,
        "maturity": maturity,
        "same_cycle_control": same_cycle_control,
        "collection": scoped_collection,
        "denominators": scoped_denominators,
        "actionability": actionability,
        "eligibility": eligibility,
        "deterministic_gates": deterministic,
        "coverage": coverage,
        "conflicts": deterministic["conflicts"],
        "exclusions": deterministic["exclusions"],
        "independent_validation": deterministic["independent_validation"],
        "agent_slice": agent_slice,
        "stage_feedback": scoped_stage_feedback,
        "instructions": {
            "use": "diagnosis_and_shadow_hypotheses_only",
            "do_not_use": "change_thresholds_gates_sizing_risk_execution_or_promotion",
            "missing_or_conflicting": "keep_unavailable_and_request_exact_lineage",
        },
    }


def _signal_stat(items: list[dict[str, Any]], *, key: str | None = None) -> dict[str, Any]:
    resolved = _resolved_signals(items)
    winners = [
        item
        for item in resolved
        if str((item.get("outcome") or {}).get("verdict", "")).startswith("winner")
    ]
    returns_1d = [_num((item.get("outcome") or {}).get("return_1d")) for item in resolved]
    returns_3d = [_num((item.get("outcome") or {}).get("return_3d")) for item in resolved]
    returns_5d = [_num((item.get("outcome") or {}).get("return_5d")) for item in resolved]
    returns_10d = [_num((item.get("outcome") or {}).get("return_10d")) for item in resolved]
    mfe = [_num((item.get("outcome") or {}).get("mfe_10d")) for item in resolved]
    mae = [_num((item.get("outcome") or {}).get("mae_10d")) for item in resolved]

    def avg(values: list[float | None]) -> float | None:
        clean = [value for value in values if value is not None]
        return round(sum(clean) / len(clean), 4) if clean else None

    out = {
        "signals": len(items),
        "resolved": len(resolved),
        "pending": len(items) - len(resolved),
        "win_rate": round(len(winners) / len(resolved), 4) if resolved else None,
        "avg_return_1d": avg(returns_1d),
        "avg_return_3d": avg(returns_3d),
        "avg_return_5d": avg(returns_5d),
        "avg_return_10d": avg(returns_10d),
        "avg_mfe_10d": avg(mfe),
        "avg_mae_10d": avg(mae),
    }
    if key is not None:
        out["key"] = key
    return out


def build_learning_status(store: Store, *, since_date: str = "2026-04-01", limit: int = 1000) -> dict[str, Any]:
    reader = getattr(store, "iter_signal_outcomes", None)
    incoming = reader(limit=limit, since_date=since_date) if callable(reader) else store.signal_outcomes(limit=limit, since_date=since_date)
    try:
        signals = [_compact_learning_metric_signal(signal) for signal in incoming]
    finally:
        close = getattr(incoming, "close", None)
        if callable(close):
            close()
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_combo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    verdicts = Counter()
    decisions = Counter()
    for signal in signals:
        decisions[signal["decision"]] += 1
        verdict = (signal.get("outcome") or {}).get("verdict", "pending")
        verdicts[verdict] += 1
        for tag in _indicator_tags(signal):
            by_tag[tag].append(signal)
        by_combo[_combo_key(signal)].append(signal)
        by_setup[_setup_key(signal)].append(signal)

    indicator_stats = []
    for tag, items in by_tag.items():
        stat = _signal_stat(items, key=tag)
        stat["tag"] = stat.pop("key")
        indicator_stats.append(stat)
    combo_stats = []
    for combo, items in by_combo.items():
        stat = _signal_stat(items, key=combo)
        combo_stats.append(stat)
    setup_stats = []
    for setup, items in by_setup.items():
        stat = _signal_stat(items, key=setup)
        stat["setup"] = stat.pop("key")
        setup_stats.append(stat)
    indicator_stats.sort(
        key=lambda item: (
            item["resolved"],
            item["win_rate"] if item["win_rate"] is not None else -1,
            item["avg_return_5d"] if item["avg_return_5d"] is not None else -1,
        ),
        reverse=True,
    )
    combo_stats.sort(
        key=lambda item: (
            item["resolved"],
            item["win_rate"] if item["win_rate"] is not None else -1,
            item["avg_return_5d"] if item["avg_return_5d"] is not None else -1,
        ),
        reverse=True,
    )
    setup_stats.sort(
        key=lambda item: (
            item["resolved"],
            item["avg_return_5d"] if item["avg_return_5d"] is not None else -1,
            item["win_rate"] if item["win_rate"] is not None else -1,
        ),
        reverse=True,
    )
    resolved_total = len(_resolved_signals(signals))
    horizon_maturity = {
        f"{h}d": sum(
            1
            for signal in signals
            if ((signal.get("outcome") or {}).get("matured_horizons", {}) or {}).get(f"{h}d")
            or (signal.get("outcome") or {}).get(f"return_{h}d") is not None
        )
        for h in HORIZONS
    }
    return {
        "metric_scope": "signal",
        "portfolio_metrics": _portfolio_metrics_unavailable(),
        "since_date": since_date,
        "signals": len(signals),
        "resolved": resolved_total,
        "pending": len(signals) - resolved_total,
        "maturity": {
            "resolved_ratio": round(resolved_total / len(signals), 4) if signals else 0.0,
            "horizon_coverage": horizon_maturity,
            "enough_for_rules": resolved_total >= 50,
            "note": "usar 1d/3d para aprendizaje temprano y 5d/10d para validacion mas fuerte; no promover reglas sin evidencia suficiente",
        },
        "decisions": dict(decisions),
        "verdicts": dict(verdicts),
        "agent_learning": build_agent_learning_scoreboard(signals),
        "best_indicators": indicator_stats[:10],
        "worst_indicators": sorted(
            [item for item in indicator_stats if item["resolved"]],
            key=lambda item: (
                item["win_rate"] if item["win_rate"] is not None else 1,
                item["avg_return_5d"] if item["avg_return_5d"] is not None else 1,
            ),
        )[:10],
        "best_combinations": combo_stats[:10],
        "setup_stats": setup_stats,
        "worst_combinations": sorted(
            [item for item in combo_stats if item["resolved"]],
            key=lambda item: (
                item["win_rate"] if item["win_rate"] is not None else 1,
                item["avg_return_5d"] if item["avg_return_5d"] is not None else 1,
            ),
        )[:10],
        "worst_setups": sorted(
            [item for item in setup_stats if item["resolved"]],
            key=lambda item: (
                item["win_rate"] if item["win_rate"] is not None else 1,
                item["avg_return_5d"] if item["avg_return_5d"] is not None else 1,
            ),
        )[:5],
    }


def write_learning_report(report: dict[str, Any], reports_dir: Path, run_id: str) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"signal_learning_{run_id}.json"
    latest_path = reports_dir / "latest_signal_learning.json"
    report["path"] = str(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return report
