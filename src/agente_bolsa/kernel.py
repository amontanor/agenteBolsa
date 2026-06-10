"""Kernel inmutable de seguridad.

Este modulo concentra los limites absolutos que los agentes autonomos NUNCA
pueden modificar. Es el "suelo" del sistema: una ultima validacion, adicional e
independiente de ``tools/risk.py``, que se ejecuta justo antes de enviar
cualquier orden al broker. ``risk.py`` sigue siendo el limite operativo (mas
estricto y ajustable por los agentes); el kernel es el limite que jamas cede.

Reglas de oro (ver ``docs/architecture.md`` y la seccion 0.3 del plan):
- Ningun cambio autonomo puede tocar este archivo (esta en BLOCKED_PREFIXES).
- Ninguna orden puede llegar al broker sin pasar ``kernel_check_order``.
- La integridad del kernel y de los archivos criticos se verifica cada sesion
  mediante ``kernel_integrity`` contra un manifest sellado manualmente.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones de tipo.
    from .config import Settings


MANIFEST_FILENAME = "kernel_manifest.json"


@dataclass(frozen=True)
class KernelLimits:
    """Limites absolutos e inmutables del sistema.

    No se leen de ``Settings`` a proposito: son el suelo que los agentes no
    pueden tunear. ``risk.py`` puede ser mas estricto, nunca mas laxo que esto.
    """

    absolute_max_drawdown_pct: float = 0.20
    absolute_max_daily_loss_pct: float = 0.05
    absolute_max_position_exposure: float = 0.15
    absolute_max_portfolio_exposure: float = 1.0
    live_trading_locked: bool = True
    min_reward_risk: float = 1.2


# Archivos cuya integridad vigila el kernel (rutas relativas al raiz del repo).
_CRITICAL_RELATIVE_FILES = (
    "src/agente_bolsa/kernel.py",
    "src/agente_bolsa/tools/broker.py",
    "src/agente_bolsa/tools/execution.py",
    ".env",
)


def _repo_root() -> Path:
    # kernel.py vive en <repo>/src/agente_bolsa/kernel.py
    return Path(__file__).resolve().parents[2]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    payload = plan.get("payload")
    return payload if isinstance(payload, dict) else {}


def _plan_checks(plan: dict[str, Any]) -> dict[str, Any]:
    payload = _plan_payload(plan)
    risk_decision = payload.get("risk_decision")
    if isinstance(risk_decision, dict):
        checks = risk_decision.get("checks")
        if isinstance(checks, dict):
            return checks
    return {}


def _first_float(*candidates: Any) -> float | None:
    for candidate in candidates:
        value = _as_float(candidate)
        if value is not None:
            return value
    return None


def _portfolio_equity(portfolio: Any) -> float | None:
    if portfolio is None:
        return None
    return _as_float(getattr(portfolio, "portfolio_value", None))


def _portfolio_exposure(portfolio: Any) -> float | None:
    """Exposicion agregada (valor de mercado de posiciones / equity)."""

    equity = _portfolio_equity(portfolio)
    if not equity or equity <= 0:
        return None
    positions = getattr(portfolio, "positions", None) or []
    total = 0.0
    for position in positions:
        market_value = _as_float(getattr(position, "market_value", None))
        if market_value is not None:
            total += abs(market_value)
    return total / equity


def kernel_check_order(
    plan: dict[str, Any],
    portfolio: Any,
    settings: "Settings",
) -> tuple[bool, str]:
    """Ultima validacion antes de enviar una orden al broker.

    Es ADICIONAL a ``risk.py``: aunque ``risk.py`` apruebe, el kernel puede
    bloquear. Devuelve ``(True, motivo)`` si la orden puede continuar o
    ``(False, motivo)`` si el kernel la corta. Es defensiva: si falta contexto
    para un gate concreto, no inventa datos, pero aplica todos los que si puede
    verificar con la informacion disponible en ``plan`` y ``portfolio``.
    """

    limits = KernelLimits()
    payload = _plan_payload(plan)
    checks = _plan_checks(plan)
    side = str(plan.get("side") or "").lower()

    # 1) Bloqueo absoluto de live trading. El kernel mantiene live cerrado salvo
    #    desbloqueo humano explicito (ALLOW_LIVE_TRADING). live_trading_locked es
    #    el cerrojo del propio kernel.
    trading_mode = str(getattr(settings, "trading_mode", "paper") or "paper").lower()
    allow_live = bool(getattr(settings, "allow_live_trading", False))
    if trading_mode == "live" and (limits.live_trading_locked and not allow_live):
        return False, "kernel: live trading bloqueado por el cerrojo inmutable."

    # 2) Drawdown absoluto y perdida diaria absoluta (cortan cualquier nueva orden).
    drawdown_pct = _first_float(
        payload.get("current_drawdown_pct"),
        checks.get("current_drawdown_pct"),
        checks.get("drawdown_pct"),
    )
    if drawdown_pct is not None and abs(drawdown_pct) > limits.absolute_max_drawdown_pct:
        return (
            False,
            (
                f"kernel: drawdown {abs(drawdown_pct):.4f} supera el maximo absoluto "
                f"{limits.absolute_max_drawdown_pct:.4f}."
            ),
        )

    daily_loss_pct = _first_float(
        payload.get("daily_loss_pct"),
        checks.get("daily_loss_pct"),
    )
    if daily_loss_pct is not None and abs(daily_loss_pct) > limits.absolute_max_daily_loss_pct:
        return (
            False,
            (
                f"kernel: perdida diaria {abs(daily_loss_pct):.4f} supera el maximo "
                f"absoluto {limits.absolute_max_daily_loss_pct:.4f}."
            ),
        )

    # Las ventas/salidas reducen riesgo: pasados los cerrojos globales, no se
    # bloquean por gates de exposicion ni de reward/risk.
    if side == "sell":
        return True, "kernel: venta dentro de los limites absolutos."

    # 3) Exposicion por posicion (notional / equity).
    notional = _first_float(plan.get("notional"), payload.get("notional"))
    equity = _first_float(
        payload.get("portfolio_equity"),
        checks.get("portfolio_equity"),
        _portfolio_equity(portfolio),
    )
    if notional is not None and equity and equity > 0:
        position_exposure = notional / equity
        if position_exposure > limits.absolute_max_position_exposure:
            return (
                False,
                (
                    f"kernel: exposicion por posicion {position_exposure:.4f} supera el "
                    f"maximo absoluto {limits.absolute_max_position_exposure:.4f}."
                ),
            )

        # 4) Exposicion agregada de cartera proyectada.
        current_exposure = _first_float(
            checks.get("projected_portfolio_exposure"),
            checks.get("current_portfolio_exposure"),
            _portfolio_exposure(portfolio),
        )
        if current_exposure is not None:
            base = current_exposure
            # projected_portfolio_exposure ya incluye la posicion; el resto no.
            if checks.get("projected_portfolio_exposure") is None:
                base = current_exposure + position_exposure
            if base > limits.absolute_max_portfolio_exposure:
                return (
                    False,
                    (
                        f"kernel: exposicion de cartera proyectada {base:.4f} supera el "
                        f"maximo absoluto {limits.absolute_max_portfolio_exposure:.4f}."
                    ),
                )

    # 5) Ratio beneficio/riesgo minimo absoluto.
    entry = _first_float(payload.get("entry_price"), checks.get("entry_price"))
    stop = _first_float(payload.get("stop_loss"), checks.get("stop_loss"))
    take = _first_float(payload.get("take_profit"), checks.get("take_profit"))
    reward_risk = _first_float(checks.get("reward_risk"))
    if reward_risk is None and entry is not None and stop is not None and take is not None:
        downside = entry - stop
        upside = take - entry
        if downside > 0:
            reward_risk = upside / downside
    if reward_risk is not None and reward_risk + 1e-9 < limits.min_reward_risk:
        return (
            False,
            (
                f"kernel: ratio beneficio/riesgo {reward_risk:.4f} inferior al minimo "
                f"absoluto {limits.min_reward_risk:.4f}."
            ),
        )

    return True, "kernel: orden dentro de los limites absolutos."


def _sha256_file(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except (OSError, FileNotFoundError):
        return None
    return hashlib.sha256(data).hexdigest()


def _critical_file_hashes() -> dict[str, str | None]:
    root = _repo_root()
    return {rel: _sha256_file(root / rel) for rel in _CRITICAL_RELATIVE_FILES}


def kernel_manifest_path(settings: "Settings") -> Path:
    return settings.state_dir / MANIFEST_FILENAME


def kernel_seal(settings: "Settings") -> dict[str, Any]:
    """Regenera el manifest de integridad. Solo se invoca manualmente."""

    from datetime import datetime, timezone

    hashes = _critical_file_hashes()
    manifest = {
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "files": hashes,
    }
    path = kernel_manifest_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return {"path": str(path), **manifest}


def kernel_integrity(settings: "Settings") -> dict[str, Any]:
    """Calcula los hashes actuales y los compara con el manifest sellado.

    Si no existe manifest, devuelve ``status="unsealed"`` sin violaciones (no se
    puede verificar lo que nunca se sello). Si existe, marca cada archivo como
    ``match``/mismatch y agrega la lista de violaciones.
    """

    path = kernel_manifest_path(settings)
    current = _critical_file_hashes()
    if not path.exists():
        return {
            "status": "unsealed",
            "ok": False,
            "sealed_at": None,
            "violations": [],
            "files": {rel: {"expected": None, "actual": actual, "match": None} for rel, actual in current.items()},
        }

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "manifest_unreadable",
            "ok": False,
            "sealed_at": None,
            "violations": [f"manifest ilegible: {exc}"],
            "files": {},
        }

    expected_files = manifest.get("files", {}) if isinstance(manifest, dict) else {}
    files: dict[str, Any] = {}
    violations: list[str] = []
    for rel, actual in current.items():
        expected = expected_files.get(rel)
        match = expected == actual
        files[rel] = {"expected": expected, "actual": actual, "match": match}
        if not match:
            violations.append(rel)

    return {
        "status": "ok" if not violations else "violation",
        "ok": not violations,
        "sealed_at": manifest.get("sealed_at") if isinstance(manifest, dict) else None,
        "violations": violations,
        "files": files,
    }
