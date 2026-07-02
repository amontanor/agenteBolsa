import json

from scripts.core_sleeve_parity_check import ParityInputs, build_parity_report


def test_core_sleeve_parity_check_accepts_clean_synthetic_logs(tmp_path):
    core_log = tmp_path / "core_sleeve_log.jsonl"
    overlay_log = tmp_path / "overlay_shadow_log.jsonl"
    config_path = tmp_path / "core_sleeve.json"
    config_path.write_text(json.dumps({"target_vol": 0.12}), encoding="utf-8")
    core_log.write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T10:00:00+00:00",
                "status": "would_submit",
                "data_date": "2026-07-01",
                "realized_vol_annualized": 0.2,
                "exposure": 0.6,
                "config": {"target_vol": 0.12},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    overlay_log.write_text(
        json.dumps(
            {
                "as_of": "2026-07-02T10:00:01+00:00",
                "data_date": "2026-07-01",
                "realized_vol_annualized": 0.2,
                "target_exposures": {"vol_target_12pct": 0.6},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_parity_report(ParityInputs(core_log=core_log, overlay_log=overlay_log, config_path=config_path))

    assert report["ok"] is True
    assert report["rows_checked"] == 1
    assert report["rows"][0]["issues"] == []
    assert report["rows"][0]["core_overlay_delta"] == 0
    assert report["rows"][0]["core_recalc_delta"] == 0


def test_core_sleeve_parity_check_reports_divergence(tmp_path):
    core_log = tmp_path / "core_sleeve_log.jsonl"
    overlay_log = tmp_path / "overlay_shadow_log.jsonl"
    config_path = tmp_path / "core_sleeve.json"
    config_path.write_text(json.dumps({"target_vol": 0.12}), encoding="utf-8")
    core_log.write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T10:00:00+00:00",
                "status": "would_submit",
                "data_date": "2026-07-01",
                "realized_vol_annualized": 0.2,
                "exposure": 0.6,
                "config": {"target_vol": 0.12},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    overlay_log.write_text(
        json.dumps(
            {
                "as_of": "2026-07-02T10:00:01+00:00",
                "data_date": "2026-07-01",
                "realized_vol_annualized": 0.2,
                "target_exposures": {"vol_target_12pct": 0.610001},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_parity_report(ParityInputs(core_log=core_log, overlay_log=overlay_log, config_path=config_path))

    assert report["ok"] is False
    assert report["rows_checked"] == 1
    assert "core_overlay_exposure_divergence" in report["rows"][0]["issues"]
