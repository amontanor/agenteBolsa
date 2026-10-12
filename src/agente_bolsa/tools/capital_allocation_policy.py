"""Human-gated paper allocation policy; no provider or execution authority."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from .capital_ladder import STAGE_LIMITS, evaluate_stage_promotion

SCHEMA_VERSION = "capital-allocation.v1"
POLICY_FILENAME = "capital_allocation_policy.json"
STAGES = {2: {"exposure": 0.15, "order_fraction": 0.025, "daily_buys": 3},
          3: {"exposure": 0.20, "order_fraction": 0.025, "daily_buys": 4},
          4: {"exposure": 0.25, "order_fraction": 0.025, "daily_buys": 4}}
REGISTERED_AT = "2026-10-12T11:54:10Z"
BASELINE_SOURCE_TREE = "a7167bca1b9387c40eb37d32d3497505dd573bf7"
_CONTRACT_HASH = hashlib.sha256(b"".join(
    (Path(__file__).parent / name).read_bytes()
    for name in ("capital_allocation_policy.py", "capital_ladder.py", "position_sizing.py", "trade_decision.py")
)).hexdigest()
_SOURCE_RECEIPT_CACHE: dict[tuple[Any, ...], bool] = {}


def receipt_content_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key not in {"content_hash", "captured_at"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evidence_content_hash(evidence: Mapping[str, Any]) -> str:
    return receipt_content_hash({key: value for key, value in evidence.items() if key != "source_receipt"})


def _verify_source_receipts(settings: Any, evidence: Mapping[str, Any], policy_hash: str, approval_id: str) -> bool:
    """Resolve canonical reviewed evidence once; never trusts documentary counts alone."""
    from agente_bolsa.storage import Store

    receipt = evidence.get("source_receipt")
    if not isinstance(receipt, Mapping) or not receipt.get("event_id") or not receipt.get("content_hash"):
        return False
    sessions = evidence.get("completed_shadow_sessions")
    if not isinstance(sessions, list) or not all(isinstance(s, Mapping) for s in sessions) or len(sessions) > 30:
        return False
    refs = [(s.get("event_id"), s.get("content_hash")) for s in sessions]
    refs.append((receipt["event_id"], receipt["content_hash"]))
    if any(not isinstance(i, str) or not isinstance(h, str) for i, h in refs) or len({i for i, _ in refs}) != len(refs):
        return False
    path = Path(settings.database_path)
    if not path.exists():
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    key = (str(path.resolve()), stat.st_dev, stat.st_ino, policy_hash, evidence_content_hash(evidence), approval_id, tuple(refs))
    if key in _SOURCE_RECEIPT_CACHE:
        return True
    store = Store(path, settings.agent_logs_dir)
    try:
        conn = store.read_connection()
        ids = [i for i, _ in refs]
        placeholders = ",".join("?" for _ in ids)
        with closing(conn.execute(f"SELECT event_id,event_type,payload_json FROM agent_events WHERE event_id IN ({placeholders}) LIMIT ?", [*ids, len(ids)])) as cursor:
            records = {r["event_id"]: (r["event_type"], json.loads(r["payload_json"])) for r in cursor}
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error):
        return False
    finally:
        store.close_read_connection()
    if len(records) != len(refs):
        return False
    for event_id, expected_hash in refs:
        event_type, payload = records[event_id]
        if not isinstance(payload, Mapping):
            return False
        if (payload.get("policy_hash") != policy_hash or payload.get("content_hash") != expected_hash
                or receipt_content_hash(payload) != expected_hash or payload.get("review_status") != "verified"):
            return False
        if event_id == receipt["event_id"]:
            if (event_type != "capital_allocation_evidence_reviewed" or payload.get("approval_id") != approval_id
                    or payload.get("evidence_hash") != evidence_content_hash(evidence)):
                return False
        else:
            expected_session = next(s for s in sessions if s["event_id"] == event_id)
            expected_session = {k: v for k, v in expected_session.items() if k not in {"event_id", "content_hash"}}
            if event_type != "capital_allocation_session_reviewed" or payload.get("session") != expected_session:
                return False
    if len(_SOURCE_RECEIPT_CACHE) >= 32:
        _SOURCE_RECEIPT_CACHE.clear()
    _SOURCE_RECEIPT_CACHE[key] = True
    return True


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.utcoffset() is not None else None


def policy_fingerprint(policy: Mapping[str, Any]) -> str:
    """Bind approval/evidence to parameters, not mutable operational mode."""
    body = {key: policy.get(key) for key in (
        "schema_version", "stage", "registered_at", "enable_adds", "quality_policy_hash", "quality_policy_approved", "baseline_source_tree"
    )}
    body["stage_limits"] = STAGES
    body["source_contract_hash"] = _CONTRACT_HASH
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evaluate_allocation_readiness(
    evidence: Mapping[str, Any], *, stage: int, policy_hash: str, now: datetime,
) -> dict[str, Any]:
    """Evaluate immutable evidence; never promotes or changes configuration."""
    reasons: list[str] = []
    if stage not in STAGES:
        return {"eligible": False, "status": "blocked", "reasons": ["stage_invalid"]}
    if now.utcoffset() is None:
        return {"eligible": False, "status": "blocked", "reasons": ["clock_invalid"]}
    if evidence.get("policy_hash") != policy_hash:
        reasons.append("evidence_policy_mismatch")
    as_of = _aware(evidence.get("as_of"))
    registered = _aware(evidence.get("policy_registered_at"))
    if as_of is None or as_of > now:
        reasons.append("evidence_time_invalid")
    if registered is None or as_of is None or registered > as_of:
        reasons.append("policy_registration_unavailable")
    sessions = evidence.get("completed_shadow_sessions")
    if not isinstance(sessions, list) or len(sessions) < 5:
        reasons.append("five_shadow_sessions_required")
    else:
        ids: set[str] = set()
        from agente_bolsa.market_calendar import MarketCalendar

        calendar = MarketCalendar()._calendar
        for session in sessions:
            if not isinstance(session, Mapping):
                reasons.append("shadow_session_invalid")
                continue
            session_id = session.get("session_id")
            ended = _aware(session.get("closed_at"))
            if (not isinstance(session_id, str) or not session_id or session_id in ids
                    or session.get("calendar") != "XNYS" or session.get("status") != "completed"
                    or ended is None or as_of is None or ended > as_of
                    or registered is None or ended <= registered
                    or session.get("policy_hash") != policy_hash
                    or not session.get("event_id") or not session.get("content_hash")):
                reasons.append("shadow_session_invalid")
            try:
                schedule = calendar.schedule(start_date=session_id, end_date=session_id) if calendar is not None else None
                actual_close = schedule.iloc[0]["market_close"].to_pydatetime() if schedule is not None and not schedule.empty else None
                actual_open = schedule.iloc[0]["market_open"].to_pydatetime() if actual_close is not None else None
                coverage_start = _aware(session.get("coverage_start"))
                coverage_end = _aware(session.get("coverage_end"))
                if (actual_close is None or ended != actual_close or coverage_start is None
                        or coverage_end is None or coverage_start > actual_open or coverage_end < actual_close
                        or coverage_start < registered):
                    reasons.append("xnys_session_close_unverified")
            except (ValueError, TypeError, KeyError, IndexError):
                reasons.append("xnys_session_close_unverified")
            if isinstance(session_id, str):
                ids.add(session_id)
    coverage = _number(evidence.get("lineage_coverage"))
    if coverage is None or not 0.95 <= coverage <= 1:
        reasons.append("lineage_coverage_below_95pct")
    if evidence.get("quantities_reconciled") is not True:
        reasons.append("quantities_unreconciled")
    if evidence.get("broker_protection_reconciled") is not True:
        reasons.append("broker_protection_unreconciled")
    for field in ("critical_alerts", "missing_critical_data", "material_loss_windows"):
        if type(evidence.get(field)) is not int or evidence[field] != 0:
            reasons.append(field + "_unavailable_or_nonzero")
    # Existing ladder requirements remain necessary and cannot be weakened.
    promotion = evaluate_stage_promotion(dict(evidence), target_stage=stage, human_approved=True)
    reasons.extend(promotion["reasons"])
    if stage >= 3:
        windows = evidence.get("comparison_windows")
        if not isinstance(windows, list) or len(windows) != 2:
            reasons.append("two_comparable_windows_required")
        else:
            bounds = []
            for window in windows:
                if not isinstance(window, Mapping):
                    reasons.append("comparison_window_invalid")
                    continue
                start, end = _aware(window.get("start")), _aware(window.get("end"))
                excess = _number(window.get("net_excess_vs_control"))
                dd = _number(window.get("drawdown_deterioration"))
                if (start is None or end is None or start >= end or as_of is None or end > as_of
                        or registered is None or start < registered
                        or excess is None or excess <= 0 or dd is None or dd > 0.01
                        or window.get("costs_included") is not True
                        or window.get("identities_verified") is not True
                        or window.get("policy_hash") != policy_hash):
                    reasons.append("comparison_window_invalid")
                else:
                    bounds.append((start, end))
            if len(bounds) == 2:
                bounds.sort()
                if bounds[0][1] >= bounds[1][0]:
                    reasons.append("comparison_windows_overlap")
    return {"eligible": not reasons, "status": "eligible_for_human_review" if not reasons else "collecting",
            "reasons": sorted(set(reasons)), "stage": stage, "policy_hash": policy_hash,
            "active": False, "authority": "evidence_only"}


def load_capital_allocation_policy(data_dir: Path, settings: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Read only; absent policy collects shadow, invalid activation fails closed."""
    base = {"schema_version": SCHEMA_VERSION, "stage": 2, "mode": "shadow", "status": "shadow",
            "enable_adds": False, "reasons": ["activation_not_approved"], "active": False,
            "registered_at": REGISTERED_AT, "baseline_source_tree": BASELINE_SOURCE_TREE}
    path = Path(data_dir) / "config" / POLICY_FILENAME
    if not path.exists():
        return {**base, "policy_hash": policy_fingerprint(base)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {**base, "status": "blocked", "reasons": ["policy_file_invalid"]}
    if (not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION
            or type(raw.get("stage")) is not int or raw["stage"] not in STAGES
            or type(raw.get("enable_adds", False)) is not bool
            or raw.get("mode") not in {"shadow", "guarded_active"}):
        return {**base, "status": "blocked", "reasons": ["policy_schema_invalid"]}
    policy = {**base, **raw, "active": False, "status": "shadow", "reasons": []}
    fingerprint = policy_fingerprint(policy)
    policy["policy_hash"] = fingerprint
    if policy["mode"] == "shadow":
        policy["reasons"] = ["shadow_only"]
        return policy
    reasons = []
    if raw.get("registered_at") != REGISTERED_AT or raw.get("baseline_source_tree") != BASELINE_SOURCE_TREE:
        reasons.append("frozen_registration_mismatch")
    flags = {"trading_mode": "paper", "alpaca_paper": True,
             "allow_live_trading": False, "allow_auto_apply_improvements": False}
    if any(getattr(settings, key, None) != value for key, value in flags.items()):
        reasons.append("paper_flags_invalid")
    for field, cap in [("max_position_exposure", 0.05), ("max_risk_per_trade", 0.01), ("max_total_open_risk", 0.03)]:
        value = _number(getattr(settings, field, None))
        if value is None or not 0 < value <= cap:
            reasons.append("safety_limit_invalid:" + field)
    approval = raw.get("approval")
    if (not isinstance(approval, dict) or approval.get("human_approved") is not True
            or not approval.get("approval_id") or approval.get("policy_hash") != fingerprint):
        reasons.append("human_approval_required")
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict):
        reasons.append("evidence_unavailable")
    else:
        if evidence.get("policy_registered_at") != raw.get("registered_at"):
            reasons.append("policy_registration_mismatch")
        readiness = evaluate_allocation_readiness(evidence, stage=raw["stage"], policy_hash=fingerprint,
                                                 now=now or datetime.now(timezone.utc))
        reasons.extend(readiness["reasons"])
        if not reasons and not _verify_source_receipts(settings, evidence, fingerprint, approval["approval_id"]):
            reasons.append("canonical_evidence_receipts_unverified")
    policy.update(status="blocked" if reasons else "guarded_active", active=not reasons,
                  reasons=sorted(set(reasons)))
    return policy


def cap_allocation_notional(
    policy: Mapping[str, Any], *, desired_notional: float, equity: float, cash: float,
    buying_power: float, current_exposure: float, pending_exposure: float,
    planned_exposure: float, pending_buy_notional: float, planned_buy_notional: float,
    high_tier: Mapping[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Clamp an already risk-sized notional, never multiply or submit orders."""
    checks = {"schema_version": SCHEMA_VERSION, "policy_hash": policy.get("policy_hash"),
              "stage": policy.get("stage"), "mode": policy.get("status"), "margin_allowed": False}
    values = {"desired": desired_notional, "equity": equity, "cash": cash, "buying_power": buying_power,
              "current": current_exposure, "pending": pending_exposure, "planned": planned_exposure,
              "pending_cash": pending_buy_notional, "planned_cash": planned_buy_notional}
    numbers = {key: _number(value) for key, value in values.items()}
    stage = policy.get("stage")
    if stage not in STAGES or any(v is None or v < 0 for v in numbers.values()) or numbers["equity"] <= 0:
        return 0.0, {**checks, "reason": "allocation_inputs_unavailable", "status": "unavailable"}
    limits = STAGES[stage]
    fraction = limits["order_fraction"]
    score = _number(high_tier.get("score")) if high_tier else None
    if (stage >= 3 and high_tier and high_tier.get("eligible") is True
            and high_tier.get("authority") == "validated_quality"
            and high_tier.get("policy_hash") == policy.get("quality_policy_hash")
            and score is not None and score >= 85 and high_tier.get("components_complete") is True
            and high_tier.get("expectancy_validated") is True and high_tier.get("costs_included") is True
            and high_tier.get("identity_verified") is True and high_tier.get("hard_gates_passed") is True
            and high_tier.get("approval_token") and high_tier.get("evidence_id")
            and policy.get("quality_policy_approved") is True):
        fraction = 0.05
    cash_room = max(0.0, min(numbers["cash"], numbers["buying_power"])
                    - numbers["pending_cash"] - numbers["planned_cash"])
    exposure_room = max(0.0, limits["exposure"] - numbers["current"] - numbers["pending"] - numbers["planned"])
    cap = min(numbers["desired"], fraction * numbers["equity"],
              exposure_room * numbers["equity"], cash_room)
    capped = float(Decimal(str(cap)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    checks.update(status="verified", desired_notional=numbers["desired"], capped_notional=capped,
                  order_fraction=fraction, cash_room=cash_room,
                  exposure_room=exposure_room, max_exposure=limits["exposure"],
                  daily_buys=limits["daily_buys"], no_forced_buy=True)
    return capped, checks


def active_stage_limits(policy: Mapping[str, Any]) -> dict[str, Any] | None:
    if policy.get("active") is not True or policy.get("status") != "guarded_active":
        return None
    stage = policy.get("stage")
    if stage not in STAGES or STAGE_LIMITS[stage] != STAGES[stage]["exposure"]:
        return None
    return dict(STAGES[stage])
