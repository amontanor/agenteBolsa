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
import sqlite3
import sys
from datetime import datetime, timezone

TERMINAL = {
    "filled", "canceled", "cancelled", "expired", "rejected",
    "done_for_day", "replaced", "stopped",
}


def normalize_status(raw: str) -> str:
    """'OrderStatus.PENDING_NEW' -> 'pending_new'; 'filled' -> 'filled'."""
    s = str(raw or "").strip()
    if "." in s:
        s = s.split(".")[-1]
    return s.lower()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcilia broker_orders contra Alpaca.")
    parser.add_argument("--apply", action="store_true", help="Persistir los estados (por defecto dry-run).")
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    parser.add_argument("--limit", type=int, default=200, help="Maximo de ordenes a revisar.")
    args = parser.parse_args()

    try:
        from agente_bolsa.config import get_settings
        from agente_bolsa.tools.broker import BrokerClientFactory
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR importando el proyecto (¿venv activo?): {exc}", file=sys.stderr)
        return 2

    settings = get_settings()
    db_path = str(settings.database_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT broker_order_id, status, symbol, side FROM broker_orders ORDER BY created_at DESC LIMIT ?",
        (args.limit,),
    ).fetchall()

    pending = [r for r in rows if normalize_status(r["status"]) not in TERMINAL]
    print(f"Ordenes totales revisadas: {len(rows)} | no terminales: {len(pending)}")
    if not pending:
        print("No hay ordenes pendientes de reconciliar.")
        con.close()
        return 0

    try:
        client = BrokerClientFactory(settings).alpaca_trading_client()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR conectando con Alpaca: {exc}", file=sys.stderr)
        con.close()
        return 2

    changes = []
    errors = []
    for r in pending:
        oid = r["broker_order_id"]
        new_status = None
        try:
            try:
                order = client.get_order_by_id(oid)
            except Exception:  # noqa: BLE001 - fallback por client_order_id.
                order = client.get_order_by_client_id(oid)
            new_status = normalize_status(getattr(order, "status", ""))
        except Exception as exc:  # noqa: BLE001
            errors.append({"broker_order_id": oid, "error": str(exc)[:120]})
            continue
        old_status = normalize_status(r["status"])
        if new_status and new_status != old_status:
            changes.append(
                {
                    "broker_order_id": oid,
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "old": old_status,
                    "new": new_status,
                }
            )

    if args.apply and changes:
        now = datetime.now(timezone.utc).isoformat()
        for ch in changes:
            con.execute(
                "UPDATE broker_orders SET status = ? WHERE broker_order_id = ?",
                (ch["new"], ch["broker_order_id"]),
            )
        con.execute(
            "INSERT OR REPLACE INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?)",
            ("broker_orders_reconcile_last_run", json.dumps({"at": now, "updated": len(changes)}), now),
        ) if _has_runtime_state(con) else None
        con.commit()

    con.close()

    if args.json:
        print(json.dumps({"changes": changes, "errors": errors, "applied": bool(args.apply)}, indent=2, ensure_ascii=False))
    else:
        if not changes:
            print("Sin cambios de estado (todas siguen igual en Alpaca).")
        for ch in changes:
            print(f"  {ch['symbol']:<6} {ch['side']:<4} {ch['old']:>12} -> {ch['new']:<12} ({ch['broker_order_id']})")
        if errors:
            print(f"\nErrores de consulta: {len(errors)} (orden inexistente o API).")
        if changes and not args.apply:
            print("\n(DRY-RUN: usa --apply para persistir estos cambios.)")
        elif changes and args.apply:
            print(f"\nAPLICADO: {len(changes)} ordenes actualizadas.")
    return 0


def _has_runtime_state(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_state'"
    ).fetchone()
    if not row:
        return False
    cols = {r[1] for r in con.execute("PRAGMA table_info('runtime_state')")}
    return {"key", "value_json", "updated_at"}.issubset(cols)


if __name__ == "__main__":
    sys.exit(main())
