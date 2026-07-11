from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from agente_bolsa.tools.market_cycle_timing import MarketCycleTiming, summarize_market_cycle_timings


def _at(second: int) -> datetime:
    return datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc) + timedelta(seconds=second)


def test_market_cycle_timing_records_complete_cycle(tmp_path):
    timing = MarketCycleTiming(tmp_path, "cycle_complete", started_at=_at(0))
    for index, name in enumerate(("data_loading", "technical_analysis", "llm_decision", "deterministic_gates", "persistence", "report_generation")):
        timing.start(name, started_at=_at(index * 10))
        timing.finish(name, finished_at=_at((index + 1) * 10))

    report = timing.finalize("completed", finished_at=_at(65))

    assert report["cycle_id"] == "cycle_complete"
    assert report["duration_seconds"] == 65.0
    assert all(item["status"] == "completed" for item in report["stages"].values())


def test_market_cycle_timing_keeps_completed_stages_when_later_stage_fails(tmp_path):
    timing = MarketCycleTiming(tmp_path, "cycle_failed", started_at=_at(0))
    timing.start("data_loading", started_at=_at(0))
    timing.finish("data_loading", finished_at=_at(12))
    timing.start("technical_analysis", started_at=_at(12))
    timing.fail("technical_analysis", "download timeout", finished_at=_at(20))

    report = timing.finalize("failed", error="download timeout", finished_at=_at(21))

    assert report["status"] == "failed"
    assert report["stages"]["data_loading"]["duration_seconds"] == 12.0
    assert report["stages"]["technical_analysis"]["error"] == "download timeout"
    assert report["stages"]["llm_decision"]["status"] == "unavailable"


def test_market_cycle_timing_marks_omitted_stage_skipped(tmp_path):
    timing = MarketCycleTiming(tmp_path, "cycle_skipped", started_at=_at(0))
    timing.skip("llm_decision", "CrewAI omitido por parametro --skip-crew")

    report = timing.finalize("skipped", finished_at=_at(1))

    assert report["stages"]["llm_decision"] == {
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
        "status": "skipped",
        "reason": "CrewAI omitido por parametro --skip-crew",
    }


def test_market_cycle_timing_summary_handles_legacy_and_percentiles(tmp_path):
    for name, duration, stage_duration in (("one", 100.0, 20.0), ("two", 700.0, 300.0), ("three", 900.0, 500.0)):
        payload = {
            "cycle_id": name,
            "duration_seconds": duration,
            "stages": {"data_loading": {"status": "completed", "duration_seconds": stage_duration}},
        }
        (tmp_path / f"market_cycle_timing_{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "market_cycle_timing_legacy.json").write_text(json.dumps({"cycle_id": "legacy"}), encoding="utf-8")

    summary = summarize_market_cycle_timings(tmp_path)

    assert summary["sample_available"] == 3
    assert summary["legacy_unavailable"] == 1
    assert summary["total_duration_seconds"] == {"p50": 700.0, "p95": 900.0, "max": 900.0}
    assert summary["over_600_seconds"] == {"count": 2, "pct": 0.6667}
    assert summary["dominant_stage"] == {"p50": "data_loading", "p95": "data_loading"}


def test_market_cycle_timing_summary_is_unavailable_without_sample(tmp_path):
    summary = summarize_market_cycle_timings(tmp_path)

    assert summary["status"] == "unavailable"
    assert summary["sample_available"] == 0
    assert summary["total_duration_seconds"]["p50"] is None


def test_market_cycle_timing_keeps_skipped_segment_with_completed_work(tmp_path):
    timing = MarketCycleTiming(tmp_path, "segments", started_at=_at(0))
    timing.skip_segment("llm_decision", "crew_reasoning", "CrewAI omitido por parametro --skip-crew")
    timing._append_segment("llm_decision", "structured_recommendations", _at(2), _at(5), "completed")

    report = timing.finalize("completed", finished_at=_at(8))

    assert [item["name"] for item in report["stages"]["llm_decision"]["segments"]] == [
        "crew_reasoning",
        "structured_recommendations",
    ]
    assert report["stages"]["llm_decision"]["status"] == "completed"


def test_market_cycle_timing_deduplicates_overlapping_segments(tmp_path):
    timing = MarketCycleTiming(tmp_path, "overlap", started_at=_at(0))
    timing._append_segment("data_loading", "one", _at(0), _at(10), "completed")
    timing._append_segment("technical_analysis", "two", _at(5), _at(15), "completed")

    report = timing.finalize("completed", finished_at=_at(20))

    assert report["segment_overlap_count"] == 1
    assert report["tracked_duration_seconds"] == 15.0
    assert report["unattributed_duration_seconds"] == 5.0
