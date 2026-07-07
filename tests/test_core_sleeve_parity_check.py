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


def test_multiday_parity_check_hides_nothing(tmp_path):
    core_log = tmp_path / "core_sleeve_log.jsonl"
    overlay_log = tmp_path / "overlay_shadow_log.jsonl"
    config_path = tmp_path / "core_sleeve.json"
    config_path.write_text(json.dumps({"target_vol": 0.12}), encoding="utf-8")

    dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
    core_lines = []
    overlay_lines = []
    for i, d in enumerate(dates):
        exposure = 0.6
        overlay_exposure = 0.6
        if d == "2026-07-02":
            exposure = 0.5
            overlay_exposure = 0.500002  # divergence above default tolerance 1e-6
        core_lines.append(
            json.dumps(
                {
                    "created_at": f"2026-07-{2+i:02d}T10:00:00+00:00",
                    "status": "would_submit",
                    "data_date": d,
                    "realized_vol_annualized": 0.2,
                    "exposure": exposure,
                    "config": {"target_vol": 0.12},
                }
            )
        )
        overlay_lines.append(
            json.dumps(
                {
                    "as_of": f"2026-07-{2+i:02d}T10:00:01+00:00",
                    "data_date": d,
                    "realized_vol_annualized": 0.2,
                    "target_exposures": {"vol_target_12pct": overlay_exposure},
                }
            )
        )

    core_log.write_text("\n".join(core_lines) + "\n", encoding="utf-8")
    overlay_log.write_text("\n".join(overlay_lines) + "\n", encoding="utf-8")

    report = build_parity_report(ParityInputs(core_log=core_log, overlay_log=overlay_log, config_path=config_path))

    assert report["rows_checked"] == 3
    assert report["rows"][0]["issues"] == []
    assert report["rows"][2]["issues"] == []
    assert "core_overlay_exposure_divergence" in report["rows"][1]["issues"]
    assert report["ok"] is False
