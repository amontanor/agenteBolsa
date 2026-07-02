"""SPY core sleeve controlled by the validated vol-target overlay."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import get_settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.research.overlay_shadow import run_overlay_shadow_once
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.execution import submit_paper_order_plan

CORE_SLEEVE_SYMBOL = "SPY"
DEFAULT_CORE_SLEEVE_CONFIG = {
    "enabled": False,
    "dry_run": True,
    "sleeve_fraction": 0.30,
    "rebalance_band_pp": 5,
    "target_vol": 0.12,
}
DEFAULT_CONFIG_PATH = Path("data/config/core_sleeve.json")
DEFAULT_LOG_DIR = Path("data/research/core_sleeve")


@dataclass(frozen=True)
class CoreSleeveConfig:
    enabled: bool = False
    dry_run: bool = True
    sleeve_fraction: float = 0.30
    rebalance_band_pp: float = 5.0
    target_vol: float = 0.12


@dataclass(frozen=True)
class CoreSleeveDecision:
    data_date: str
    equity: float
    price: float
    exposure: float
    sleeve_fraction: float
    target_notional: float
    current_notional: float
    max_sleeve_notional: float
    rebalance_band_notional: float
    delta_notional: float
    order: dict[str, Any] | None
    reason: str


def load_core_sleeve_config(config_path: Path, *, create: bool = True) -> CoreSleeveConfig:
    if create and not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULT_CORE_SLEEVE_CONFIG, indent=2) + "\n", encoding="utf-8")
    payload = dict(DEFAULT_CORE_SLEEVE_CONFIG)
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"Configuracion core sleeve invalida: {config_path}")
        payload.update(raw)
    return CoreSleeveConfig(
        enabled=bool(payload.get("enabled")),
        dry_run=bool(payload.get("dry_run", True)),
        sleeve_fraction=_clip(float(payload.get("sleeve_fraction", 0.30)), 0.0, 1.0),
        rebalance_band_pp=max(0.0, float(payload.get("rebalance_band_pp", 5.0))),
        target_vol=max(0.0, float(payload.get("target_vol", 0.12))),
    )


def calculate_core_sleeve_decision(
    *,
    portfolio: PortfolioSnapshot | dict[str, Any],
    config: CoreSleeveConfig,
    exposure: float,
    price: float,
    data_date: str,
    already_rebalanced: bool = False,
) -> CoreSleeveDecision:
    equity = max(0.0, _portfolio_equity(portfolio))
    safe_price = max(0.0, float(price or 0.0))
    sleeve_fraction = _clip(float(config.sleeve_fraction), 0.0, 1.0)
    safe_exposure = _clip(float(exposure or 0.0), 0.0, 1.0)
    max_sleeve_notional = equity * sleeve_fraction
    target_notional = min(max_sleeve_notional, equity * sleeve_fraction * safe_exposure)
    current_notional = max(0.0, _long_symbol_notional(portfolio, CORE_SLEEVE_SYMBOL))
    band_notional = max_sleeve_notional * (float(config.rebalance_band_pp) / 100.0)
    delta = target_notional - current_notional
    order = None
    reason = "within_rebalance_band"

    if already_rebalanced:
        reason = "already_rebalanced_today"
    elif equity <= 0:
        reason = "missing_equity"
    elif safe_price <= 0:
        reason = "missing_price"
    elif abs(delta) > band_notional:
        if delta > 0:
            notional = min(delta, max(0.0, max_sleeve_notional - current_notional))
            order = _order_payload(side="buy", notional=notional, price=safe_price)
            reason = "buy_to_target"
        elif current_notional > 0:
            sell_notional = min(abs(delta), current_notional)
            order = _order_payload(side="sell", notional=sell_notional, price=safe_price)
            reason = "sell_to_target"

    return CoreSleeveDecision(
        data_date=data_date,
        equity=round(equity, 6),
        price=round(safe_price, 6),
        exposure=round(safe_exposure, 6),
        sleeve_fraction=round(sleeve_fraction, 6),
        target_notional=round(target_notional, 2),
        current_notional=round(current_notional, 2),
        max_sleeve_notional=round(max_sleeve_notional, 2),
        rebalance_band_notional=round(band_notional, 2),
        delta_notional=round(delta, 2),
        order=order,
        reason=reason,
    )


def run_core_sleeve_once(
    *,
    config_path: Path | None = None,
    log_dir: Path | None = None,
    overlay_runner: Callable[..., dict[str, Any]] = run_overlay_shadow_once,
    portfolio_loader: Callable[[], PortfolioSnapshot] | None = None,
    order_submitter: Callable[..., dict[str, Any]] = submit_paper_order_plan,
) -> dict[str, Any]:
    settings = get_settings()
    config_path = config_path or settings.data_dir / "config" / "core_sleeve.json"
    log_dir = log_dir or settings.data_dir / "research" / "core_sleeve"
    config = load_core_sleeve_config(config_path)
    overlay = overlay_runner()
    observation = overlay.get("observation") or overlay
    exposure = float((observation.get("target_exposures") or {}).get("vol_target_12pct") or 0.0)
    price = float(observation.get("price") or 0.0)
    data_date = str(observation.get("data_date") or date.today().isoformat())

    if not config.enabled:
        payload = _log_payload(config=config, observation=observation, decision=None, status="disabled")
        append_core_sleeve_log(payload, log_dir)
        return {"ok": True, "status": "disabled", "config_path": str(config_path), "log_path": str(log_dir / "core_sleeve_log.jsonl")}

    already = has_core_sleeve_rebalance_for_date(log_dir / "core_sleeve_log.jsonl", data_date)
    portfolio = portfolio_loader() if portfolio_loader else BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    decision = calculate_core_sleeve_decision(
        portfolio=portfolio,
        config=config,
        exposure=exposure,
        price=price,
        data_date=data_date,
        already_rebalanced=already,
    )
    payload = _log_payload(config=config, observation=observation, decision=decision, status="no_order")
    if decision.order is None:
        append_core_sleeve_log(payload, log_dir)
        return {"ok": True, "status": "no_order", "decision": asdict(decision), "log_path": str(log_dir / "core_sleeve_log.jsonl")}

    if config.dry_run:
        payload["status"] = "would_submit"
        append_core_sleeve_log(payload, log_dir)
        return {"ok": True, "status": "would_submit", "decision": asdict(decision), "log_path": str(log_dir / "core_sleeve_log.jsonl")}

    market_status = MarketCalendar(settings.market_calendar, settings.local_timezone).status()
    payload["market"] = market_status.as_dict()
    if not market_status.is_open:
        payload["status"] = "market_closed"
        append_core_sleeve_log(payload, log_dir)
        return {"ok": False, "status": "market_closed", "decision": asdict(decision), "market": market_status.as_dict()}

    submitted = order_submitter(settings, decision.order, client_order_id=f"core-sleeve-{data_date.replace('-', '')}")
    payload["status"] = "submitted"
    payload["submitted_order"] = submitted
    append_core_sleeve_log(payload, log_dir)
    return {"ok": True, "status": "submitted", "decision": asdict(decision), "submitted_order": submitted}


def append_core_sleeve_log(payload: dict[str, Any], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "core_sleeve_log.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return path


def has_core_sleeve_rebalance_for_date(log_path: Path, data_date: str) -> bool:
    if not log_path.exists():
        return False
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("data_date") == data_date and payload.get("status") in {"would_submit", "submitted"}:
            return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ejecuta la manga core SPY en modo aislado.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_core_sleeve_once(config_path=Path(args.config), log_dir=Path(args.log_dir))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Core sleeve status={result.get('status')} log={result.get('log_path', '')}")
    return 0


def _log_payload(
    *,
    config: CoreSleeveConfig,
    observation: dict[str, Any],
    decision: CoreSleeveDecision | None,
    status: str,
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "symbol": CORE_SLEEVE_SYMBOL,
        "data_date": observation.get("data_date"),
        "price": observation.get("price"),
        "realized_vol_annualized": observation.get("realized_vol_annualized"),
        "exposure": (observation.get("target_exposures") or {}).get("vol_target_12pct"),
        "config": asdict(config),
        "decision": asdict(decision) if decision else None,
    }


def _order_payload(*, side: str, notional: float, price: float) -> dict[str, Any] | None:
    safe_notional = round(max(0.0, float(notional)), 2)
    if safe_notional <= 0:
        return None
    qty = round(safe_notional / price, 6) if price > 0 else None
    return {
        "symbol": CORE_SLEEVE_SYMBOL,
        "side": side,
        "notional": safe_notional,
        "payload": {
            "qty": qty,
            "entry_price": price,
            "source": "core_sleeve_vt12",
        },
    }


def _portfolio_equity(portfolio: PortfolioSnapshot | dict[str, Any]) -> float:
    if isinstance(portfolio, dict):
        return float(portfolio.get("portfolio_value") or portfolio.get("equity") or 0.0)
    return float(portfolio.portfolio_value or 0.0)


def _long_symbol_notional(portfolio: PortfolioSnapshot | dict[str, Any], symbol: str) -> float:
    positions = portfolio.get("positions", []) if isinstance(portfolio, dict) else portfolio.positions
    total = 0.0
    for position in positions or []:
        position_symbol = str(_position_value(position, "symbol") or "").upper()
        side = str(_position_value(position, "side") or "long").lower()
        if position_symbol == symbol and side == "long":
            total += max(0.0, float(_position_value(position, "market_value") or 0.0))
    return total


def _position_value(position: Any, key: str) -> Any:
    if isinstance(position, dict):
        return position.get(key)
    return getattr(position, key, None)


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


if __name__ == "__main__":
    raise SystemExit(main())
