"""Tests del kernel inmutable (T0.1)."""

import json
from argparse import Namespace

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.experiments import AutoApplyCodeAgent
from agente_bolsa.kernel import (
    KernelLimits,
    kernel_check_order,
    kernel_integrity,
    kernel_seal,
)
from agente_bolsa.main import command_kernel_seal
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.tools.operational_health import activate_persistent_kill_switch
from agente_bolsa.tools.risk import OrderProposal, RiskManager


def _settings(tmp_path, **overrides):
    values = {"DATA_DIR": tmp_path, "ALPACA_PAPER": True}
    values.update(overrides)
    return Settings(**values)


def _empty_portfolio(equity=100000.0):
    return PortfolioSnapshot(
        account_id="acc",
        status="ACTIVE",
        currency="USD",
        cash=equity,
        portfolio_value=equity,
        buying_power=equity,
        positions=[],
        open_orders=[],
    )


def test_kernel_approves_valid_order(tmp_path):
    settings = _settings(tmp_path)
    plan = {
        "symbol": "AAPL",
        "side": "buy",
        "notional": 5000.0,
        "payload": {
            "portfolio_equity": 100000.0,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 115.0,
        },
    }
    ok, reason = kernel_check_order(plan, _empty_portfolio(), settings)
    assert ok, reason


def test_kernel_blocks_absolute_drawdown_even_if_risk_approves(tmp_path):
    settings = _settings(tmp_path)
    # risk.py aprobaria esta orden: ratios y exposicion correctos.
    proposal = OrderProposal(
        symbol="AAPL",
        side="buy",
        notional=5000.0,
        portfolio_equity=100000.0,
        strategy_name="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )
    risk_decision = RiskManager(settings).validate_order(proposal)
    assert risk_decision.approved

    # ...pero el drawdown agregado viola el suelo absoluto del kernel (>20%).
    plan = {
        "symbol": "AAPL",
        "side": "buy",
        "notional": 5000.0,
        "payload": {
            "portfolio_equity": 100000.0,
            "current_drawdown_pct": 0.25,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 115.0,
            "risk_decision": {"approved": True, "checks": risk_decision.checks},
        },
    }
    ok, reason = kernel_check_order(plan, _empty_portfolio(), settings)
    assert not ok
    assert "drawdown" in reason


def test_kernel_blocks_position_exposure_above_absolute(tmp_path):
    settings = _settings(tmp_path)
    plan = {
        "symbol": "AAPL",
        "side": "buy",
        "notional": 20000.0,  # 20% > 15% absoluto
        "payload": {
            "portfolio_equity": 100000.0,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 115.0,
        },
    }
    ok, reason = kernel_check_order(plan, _empty_portfolio(), settings)
    assert not ok
    assert "exposicion por posicion" in reason


def test_kernel_blocks_low_reward_risk(tmp_path):
    settings = _settings(tmp_path)
    plan = {
        "symbol": "AAPL",
        "side": "buy",
        "notional": 5000.0,
        "payload": {
            "portfolio_equity": 100000.0,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 101.0,  # rr = 1/5 = 0.2 < 1.2
        },
    }
    ok, reason = kernel_check_order(plan, _empty_portfolio(), settings)
    assert not ok
    assert "beneficio/riesgo" in reason


def test_kernel_locks_live_trading(tmp_path):
    settings = _settings(tmp_path, TRADING_MODE="live", ALLOW_LIVE_TRADING=False, ALPACA_PAPER=False)
    plan = {
        "symbol": "AAPL",
        "side": "buy",
        "notional": 1000.0,
        "payload": {"portfolio_equity": 100000.0, "entry_price": 100.0, "stop_loss": 95.0, "take_profit": 115.0},
    }
    ok, reason = kernel_check_order(plan, _empty_portfolio(), settings)
    assert not ok
    assert "live" in reason


def test_kernel_allows_sell_to_reduce_risk(tmp_path):
    settings = _settings(tmp_path)
    plan = {"symbol": "AAPL", "side": "sell", "notional": 50000.0, "payload": {}}
    ok, _ = kernel_check_order(plan, _empty_portfolio(), settings)
    assert ok


def test_kernel_integrity_unsealed_then_sealed(tmp_path):
    settings = _settings(tmp_path)
    before = kernel_integrity(settings)
    assert before["status"] == "unsealed"

    sealed = kernel_seal(settings)
    assert sealed["files"]["src/agente_bolsa/kernel.py"]

    after = kernel_integrity(settings)
    assert after["status"] == "ok"
    assert after["ok"] is True
    assert after["violations"] == []


def test_kernel_integrity_detects_manifest_tampering(tmp_path):
    settings = _settings(tmp_path)
    kernel_seal(settings)

    # Alteramos el manifest para simular un hash que ya no coincide.
    manifest_path = settings.state_dir / "kernel_manifest.json"
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["src/agente_bolsa/kernel.py"] = "deadbeef"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = kernel_integrity(settings)
    assert result["status"] == "violation"
    assert "src/agente_bolsa/kernel.py" in result["violations"]


def test_kernel_seal_clears_kernel_integrity_override_when_resealed(tmp_path, monkeypatch, capsys):
    settings = _settings(tmp_path)
    activate_persistent_kill_switch(
        settings.data_dir,
        reason="kernel_integrity_violation: src/agente_bolsa/kernel.py",
        kind="kernel_integrity_violation",
    )
    monkeypatch.setattr("agente_bolsa.main.get_settings", lambda: settings)
    monkeypatch.setattr("agente_bolsa.main.configure_logging", lambda *args, **kwargs: None)

    command_kernel_seal(Namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["kill_switch_cleanup"]["cleared"] is True
    assert payload["kill_switch_cleanup"]["event_payload"]["source"] == "kernel_seal"
    assert not (settings.data_dir / "state" / "operational_kill_switch.json").exists()


def test_kernel_limits_are_frozen():
    limits = KernelLimits()
    assert limits.live_trading_locked is True
    try:
        limits.absolute_max_drawdown_pct = 0.99  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("KernelLimits deberia ser inmutable (frozen dataclass).")


def test_kernel_is_blocked_for_autonomous_edits():
    assert "src/agente_bolsa/kernel.py" in AutoApplyCodeAgent.BLOCKED_PREFIXES
