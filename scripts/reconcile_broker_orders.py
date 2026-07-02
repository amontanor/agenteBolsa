#!/usr/bin/env python3
"""Reconcilia el estado local de broker_orders contra Alpaca.

Motivacion (16-jun-2026): todas las filas de `broker_orders` quedaban en
`OrderStatus.PENDING_NEW` porque solo se guardaba el estado del momento de
envio y nunca se reconciliaba el estado final (filled/canceled/...). Eso impide
saber que ordenes se ejecutaron de verdad y rompe el enlace con el aprendizaje
(executed_buy). Este script consulta el estado real de cada orden no terminal en
Alpaca y actualiza la BD.

Por defecto corre en DRY-RUN (consulta y muestra cambios, no escribe). Usa
--apply para persistir. Requiere el entorno del proyecto (.venv) y credenciales
Alpaca paper en .env.

Uso:
    python scripts/reconcile_broker_orders.py            # dry-run
    python scripts/reconcile_broker_orders.py --apply    # persistir estados
    python scripts/reconcile_broker_orders.py --json
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcilia broker_orders contra Alpaca.")
    parser.add_argument("--apply", action="store_true", help="Persistir los estados (por defecto dry-run).")
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    parser.add_argument("--limit", type=int, default=200, help="Maximo de ordenes a revisar.")
    args = parser.parse_args()

    try:
        from agente_bolsa.config import get_settings
        from agente_bolsa.storage import Store
        from agente_bolsa.tools.broker_reconciliation import reconcile_broker_orders
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR importando el proyecto (¿venv activo?): {exc}", file=sys.stderr)
        return 2

    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    result = reconcile_broker_orders(settings, store, apply=args.apply, limit=args.limit)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Ordenes no terminales: {result['pending']} | cambios: {len(result['changes'])}")
        if not result["changes"]:
            print("Sin cambios de estado (todas siguen igual en Alpaca).")
        for ch in result["changes"]:
            print(f"  {ch['symbol']:<6} {ch['side']:<4} {ch['old']:>12} -> {ch['new']:<12} ({ch['broker_order_id']})")
        if result["errors"]:
            print(f"\nErrores de consulta: {len(result['errors'])} (orden inexistente o API).")
        if result["changes"] and not args.apply:
            print("\n(DRY-RUN: usa --apply para persistir estos cambios.)")
        elif result["changes"] and args.apply:
            print(
                f"\nAPLICADO: {len(result['changes'])} ordenes actualizadas; "
                f"signal_execution_updates={result['signal_execution_updates']}; "
                f"learning_execution_updates={result['learning_execution_updates']}."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
