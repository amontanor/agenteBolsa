from agente_bolsa import main as main_module
from agente_bolsa.config import Settings
from agente_bolsa.tools.web_evidence_ab import (
    build_web_ab_observation,
    build_web_evidence_ab_report,
    record_web_ab_observation,
)


def test_web_ab_observation_records_material_delta(tmp_path):
    observation = build_web_ab_observation(
        run_id="run_1",
        symbol="AAPL",
        news=[
            {"title": "AAPL local", "provider": "yfinance"},
            {"title": "AAPL web", "provider": "tavily"},
        ],
        combined_material_risk={"severity": "material"},
        local_material_risk={"severity": "none"},
        sentiment={"sentiment_score": 1},
    )

    record_web_ab_observation(tmp_path, observation)
    report = build_web_evidence_ab_report(tmp_path)

    assert report["summary"]["observations"] == 1
    assert report["summary"]["decisions_changed"] == 1
    assert report["summary"]["web_items"] == 1


def test_command_web_evidence_ab_outputs_json(tmp_path, monkeypatch, capsys):
    record_web_ab_observation(
        tmp_path,
        {
            "run_id": "run_1",
            "symbol": "AAPL",
            "web_items": 1,
            "material_risk_changed": True,
            "gate_changed": True,
        },
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(_env_file=None, DATA_DIR=tmp_path))
    args = type("Args", (), {"limit": None, "json": True})()

    main_module.command_web_evidence_ab(args)

    out = capsys.readouterr().out
    assert '"observations": 1' in out
    assert '"decisions_changed": 1' in out
