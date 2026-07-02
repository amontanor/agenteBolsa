from datetime import datetime, timezone

import pytest

from agente_bolsa.continuous_improvement.research_agenda import (
    add_research_hypothesis,
    build_research_agenda_snapshot,
    close_research_hypothesis,
    load_research_agenda,
    research_agenda_kpis,
)


def test_research_agenda_add_and_close_roundtrip(tmp_path):
    path = tmp_path / "research" / "research_agenda.json"
    item = add_research_hypothesis(
        path=path,
        title="test edge",
        target_date="2026-07-10",
        now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )

    closed = close_research_hypothesis(
        path=path,
        hypothesis_id=item["hypothesis_id"],
        status="matada",
        notes="sin edge neto",
        now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
    )
    rows = load_research_agenda(path)

    assert closed["status"] == "matada"
    assert closed["notes"] == "sin edge neto"
    assert rows[-1]["hypothesis_id"] == item["hypothesis_id"]
    assert rows[-1]["closed_at"] == "2026-07-03T12:00:00+00:00"


def test_research_agenda_close_requires_terminal_status(tmp_path):
    path = tmp_path / "agenda.json"
    item = add_research_hypothesis(path=path, title="x", target_date="2026-07-10")

    with pytest.raises(ValueError, match="matada o promovida"):
        close_research_hypothesis(path=path, hypothesis_id=item["hypothesis_id"], status="pendiente")


def test_research_agenda_kpis_count_current_week():
    items = [
        {
            "hypothesis_id": "h1",
            "status": "matada",
            "closed_at": "2026-07-01T12:00:00+00:00",
        },
        {
            "hypothesis_id": "h2",
            "status": "promovida",
            "closed_at": "2026-07-02T12:00:00+00:00",
        },
        {
            "hypothesis_id": "h3",
            "status": "matada",
            "closed_at": "2026-06-20T12:00:00+00:00",
        },
    ]
    experiments = [
        {"created_at": "2026-06-30T12:00:00+00:00"},
        {"created_at": "2026-07-02T12:00:00+00:00"},
        {"created_at": "2026-06-20T12:00:00+00:00"},
    ]

    kpis = research_agenda_kpis(items, experiments, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc))

    assert kpis["week_start"] == "2026-06-29"
    assert kpis["estudios_ejecutados_semana"] == 2
    assert kpis["hipotesis_matadas_semana"] == 1
    assert kpis["hipotesis_promovidas_semana"] == 1


def test_research_agenda_snapshot_seeds_required_current_hypotheses(tmp_path):
    snapshot = build_research_agenda_snapshot(
        tmp_path,
        experiments=[],
        now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )
    titles = {item["title"] for item in snapshot["items"]}

    assert {"pullback", "horizonte salida 5-10d", "telegram radar", "overlay activacion", "anomalia ORCL"} <= titles
