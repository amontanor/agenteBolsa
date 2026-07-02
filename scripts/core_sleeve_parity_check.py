"""Compare core sleeve dry-run exposure against overlay shadow and deep-study math."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CORE_LOG = Path("data/research/core_sleeve/core_sleeve_log.jsonl")
DEFAULT_OVERLAY_LOG = Path("data/research/overlay_shadow/overlay_shadow_log.jsonl")
DEFAULT_CONFIG = Path("data/config/core_sleeve.json")
DEFAULT_TOLERANCE = 1e-6
DEFAULT_TARGET_VOL = 0.12


@dataclass(frozen=True)
class ParityInputs:
    core_log: Path = DEFAULT_CORE_LOG
    overlay_log: Path = DEFAULT_OVERLAY_LOG
    config_path: Path = DEFAULT_CONFIG
    tolerance: float = DEFAULT_TOLERANCE


def build_parity_report(inputs: ParityInputs) -> dict[str, Any]:
    """Build a read-only parity report from existing JSONL artifacts."""

    core_records = _latest_records_by_date(_read_jsonl(inputs.core_log), timestamp_field="created_at")
    overlay_records = _latest_records_by_date(_read_jsonl(inputs.overlay_log), timestamp_field="as_of")
    config = _read_json(inputs.config_path)
    data_dates = sorted(set(core_records) | set(overlay_records))
    rows: list[dict[str, Any]] = []

    for data_date in data_dates:
        core = core_records.get(data_date)
        overlay = overlay_records.get(data_date)
        issues: list[str] = []
        core_exposure = _as_float((core or {}).get("exposure"))
        overlay_exposure = _as_float(((overlay or {}).get("target_exposures") or {}).get("vol_target_12pct"))
        realized_vol = _as_float((core or {}).get("realized_vol_annualized"))
        if realized_vol is None:
            realized_vol = _as_float((overlay or {}).get("realized_vol_annualized"))
        target_vol = _target_vol(core=core, config=config)
        recalculated_exposure = _recalculate_deep_exposure(target_vol=target_vol, realized_vol=realized_vol)

        if core is None:
            issues.append("missing_core_sleeve_date")
        if overlay is None:
            issues.append("missing_overlay_shadow_date")

        core_overlay_delta = _delta(core_exposure, overlay_exposure)
        core_recalc_delta = _delta(core_exposure, recalculated_exposure)
        if core_overlay_delta is not None and abs(core_overlay_delta) > inputs.tolerance:
            issues.append("core_overlay_exposure_divergence")
        if core_recalc_delta is not None and abs(core_recalc_delta) > inputs.tolerance:
            issues.append("core_deep_recalc_divergence")
        if core_exposure is None and core is not None:
            issues.append("missing_core_exposure")
        if overlay_exposure is None and overlay is not None:
            issues.append("missing_overlay_exposure")
        if recalculated_exposure is None:
            issues.append("missing_deep_recalc_inputs")

        rows.append(
            {
                "data_date": data_date,
                "ok": not issues,
                "issues": issues,
                "core_created_at": (core or {}).get("created_at"),
                "overlay_as_of": (overlay or {}).get("as_of"),
                "core_status": (core or {}).get("status"),
                "core_exposure": core_exposure,
                "overlay_exposure": overlay_exposure,
                "recalculated_exposure": recalculated_exposure,
                "core_overlay_delta": core_overlay_delta,
                "core_recalc_delta": core_recalc_delta,
                "realized_vol_annualized": realized_vol,
                "target_vol": target_vol,
            }
        )

    return {
        "ok": bool(rows) and all(row["ok"] for row in rows),
        "tolerance": inputs.tolerance,
        "core_log": str(inputs.core_log),
        "overlay_log": str(inputs.overlay_log),
        "config_path": str(inputs.config_path),
        "rows_checked": len(rows),
        "method": "target_vol / realized_vol_20d_annualized, clipped 0..1, rounded to 6 decimals.",
        "rows": rows,
    }


def format_human_report(report: dict[str, Any]) -> str:
    lines = [
        "Core sleeve parity check",
        f"ok={report['ok']} rows_checked={report['rows_checked']} tolerance={report['tolerance']}",
        f"method={report['method']}",
        "",
        "data_date   status       core      overlay   recalc    d_core_overlay  d_core_recalc  issues",
        "----------  -----------  --------  --------  --------  --------------  -------------  ------",
    ]
    for row in report["rows"]:
        issues = ",".join(row["issues"]) if row["issues"] else "-"
        lines.append(
            f"{row['data_date']:<10}  "
            f"{str(row['core_status'] or '-'):<11}  "
            f"{_fmt(row['core_exposure']):>8}  "
            f"{_fmt(row['overlay_exposure']):>8}  "
            f"{_fmt(row['recalculated_exposure']):>8}  "
            f"{_fmt(row['core_overlay_delta']):>14}  "
            f"{_fmt(row['core_recalc_delta']):>13}  "
            f"{issues}"
        )
    if not report["rows"]:
        lines.append("sin filas comparables: faltan logs core sleeve y overlay shadow")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Comprueba paridad de exposicion de la manga core SPY.")
    parser.add_argument("--core-log", default=str(DEFAULT_CORE_LOG))
    parser.add_argument("--overlay-log", default=str(DEFAULT_OVERLAY_LOG))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = build_parity_report(
        ParityInputs(
            core_log=Path(args.core_log),
            overlay_log=Path(args.overlay_log),
            config_path=Path(args.config),
            tolerance=float(args.tolerance),
        )
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_human_report(report))
    return 0 if report["ok"] else 1


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _latest_records_by_date(records: list[dict[str, Any]], *, timestamp_field: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        data_date = str(record.get("data_date") or "")
        if not data_date:
            continue
        current = latest.get(data_date)
        if current is None or str(record.get(timestamp_field) or "") >= str(current.get(timestamp_field) or ""):
            latest[data_date] = record
    return latest


def _target_vol(*, core: dict[str, Any] | None, config: dict[str, Any]) -> float:
    core_config = (core or {}).get("config") or {}
    value = _as_float(core_config.get("target_vol"))
    if value is None:
        value = _as_float(config.get("target_vol"))
    return value if value is not None else DEFAULT_TARGET_VOL


def _recalculate_deep_exposure(*, target_vol: float, realized_vol: float | None) -> float | None:
    if realized_vol is None or realized_vol <= 0:
        return None
    exposure = target_vol / realized_vol
    return round(max(0.0, min(1.0, exposure)), 6)


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 12)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
