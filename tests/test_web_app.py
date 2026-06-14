from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from agente_bolsa import __version__
from agente_bolsa.config import Settings
from agente_bolsa.llm_usage import usage_tokens
from agente_bolsa.models import OrderSnapshot, PortfolioSnapshot, PositionSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.eventing import _format_time
from agente_bolsa.web_app import (
    _ci_conversation_groups,
    _ci_global_export_payload,
    _ci_runtime_alert,
    _ci_task_activity,
    _company_study_news_files,
    _company_study_news_for_symbol,
    _company_study_export_payload,
    _company_study_global_export_payload,
    _company_study_decision_context,
    _company_study_reason,
    _company_study_signal_rows,
    _company_study_symbol_summary,
    _create_manual_opportunity_plan,
    _estimated_portfolio_value_series,
    _latest_llm_context_by_symbol,
    _latest_analyzed_news,
    _latest_daily_equity_change,
    _local_datetime,
    _llm_status_reason,
    _manual_opportunity_recommendation,
    _next_opportunity_snapshot_run_text,
    _opportunity_candidates,
    _opportunity_risk_plan,
    _opportunity_status,
    _portfolio_chart_visible_summary,
    _position_chart_start_date,
    _position_entry_date,
    _position_evolution_summary,
    _portfolio_value_series_from_alpaca,
    _sidebar_version_label,
    _single_symbol_price_frame,
    _study_price,
    _trim_portfolio_chart_range,
)


def test_usage_tokens_reads_compatible_llm_usage_object():
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
    )

    assert usage_tokens(response) == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_usage_tokens_estimates_missing_local_backend_usage():
    response = SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"recommendations":[]}')
            )
        ],
    )

    tokens = usage_tokens(response, prompt=[{"role": "user", "content": "x" * 40}])

    assert tokens["prompt_tokens"] > 0
    assert tokens["completion_tokens"] > 0
    assert tokens["total_tokens"] == tokens["prompt_tokens"] + tokens["completion_tokens"]


def test_store_daily_llm_usage_counts_requests_and_tokens(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()

    store.record_llm_usage(
        usage_id="usage_1",
        source="test",
        model="gpt-test",
        request_count=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        payload={},
    )
    store.record_llm_usage(
        usage_id="usage_2",
        source="test",
        model="gpt-test",
        request_count=1,
        prompt_tokens=7,
        completion_tokens=3,
        total_tokens=10,
        payload={},
    )

    rows = store.daily_llm_usage()

    assert rows[0]["requests"] == 2
    assert rows[0]["prompt_tokens"] == 17
    assert rows[0]["completion_tokens"] == 8
    assert rows[0]["total_tokens"] == 25


def test_portfolio_value_series_from_alpaca_builds_daily_changes():
    payload = {
        "timestamp": [
            "2026-05-08T00:00:00Z",
            "2026-05-09T00:00:00Z",
            "2026-05-10T00:00:00Z",
        ],
        "equity": [1000.0, 1015.0, 1005.0],
    }

    df = _portfolio_value_series_from_alpaca(payload, current_equity=None, start_date="2026-05-01")

    assert list(df["fecha"]) == ["2026-05-08", "2026-05-09", "2026-05-10"]
    assert list(df["valor_cartera"]) == [1000.0, 1015.0, 1005.0]
    assert list(df["P/L dia"]) == [0.0, 15.0, -10.0]
    assert list(df["fuente"]) == ["Alpaca", "Alpaca", "Alpaca"]


def test_trim_portfolio_chart_range_keeps_latest_window():
    df = _portfolio_value_series_from_alpaca(
        {
            "timestamp": [
                "2026-05-06T00:00:00Z",
                "2026-05-07T00:00:00Z",
                "2026-05-08T00:00:00Z",
                "2026-05-09T00:00:00Z",
            ],
            "equity": [1000.0, 1001.0, 1002.0, 1003.0],
        },
        current_equity=None,
        start_date="2026-05-01",
    )

    trimmed = _trim_portfolio_chart_range(df, days=2)

    assert list(trimmed["fecha"]) == ["2026-05-08", "2026-05-09"]
    assert list(trimmed["valor_cartera"]) == [1002.0, 1003.0]


def test_estimated_portfolio_value_series_still_available_as_fallback():
    history = {
        "days": [
            {"date": "2026-05-11", "realized_pl": 10.0, "open_unrealized_pl": 0.0, "buy_notional": 1000.0},
            {"date": "2026-05-12", "realized_pl": -5.0, "open_unrealized_pl": 0.0, "sell_notional": 500.0},
        ]
    }

    df = _estimated_portfolio_value_series(history, current_equity=1005.0, days=2)

    assert list(df["valor_cartera"]) == [1010.0, 1005.0]
    assert list(df["P/L dia"]) == [10.0, -5.0]
    assert list(df["fuente"]) == ["estimado", "estimado"]


def test_portfolio_chart_visible_summary_uses_visible_window_change():
    df = _portfolio_value_series_from_alpaca(
        {
            "timestamp": [
                "2026-05-06T00:00:00Z",
                "2026-05-07T00:00:00Z",
                "2026-05-08T00:00:00Z",
                "2026-05-09T00:00:00Z",
            ],
            "equity": [1000.0, 1020.0, 1010.0, 1035.0],
        },
        current_equity=None,
        start_date="2026-05-01",
    )

    trimmed = _trim_portfolio_chart_range(df, days=3)
    summary = _portfolio_chart_visible_summary(trimmed)

    assert summary["days"] == 3
    assert summary["pl"] == 15.0
    assert summary["pl_pct"] == 0.014706


def test_position_entry_date_prefers_saved_risk_order_time():
    history = {
        "risk_levels": {"AAPL": {"source_order_time": "2026-05-20T14:30:00+00:00"}},
        "trades": [{"symbol": "AAPL", "side": "buy", "time": "2026-05-19T14:30:00+00:00"}],
    }

    assert _position_entry_date(history, "aapl") == "2026-05-20"
    assert _position_chart_start_date(history, "AAPL") == "2026-05-13"


def test_position_entry_date_falls_back_to_first_buy_trade():
    history = {
        "risk_levels": {},
        "trades": [
            {"symbol": "AAPL", "side": "sell", "time": "2026-05-21T14:30:00+00:00"},
            {"symbol": "AAPL", "side": "buy", "time": "2026-05-20T14:30:00+00:00"},
            {"symbol": "AAPL", "side": "buy", "time": "2026-05-19T14:30:00+00:00"},
        ],
    }

    assert _position_entry_date(history, "AAPL") == "2026-05-19"


def test_single_symbol_price_frame_extracts_multiindex_close_volume():
    data = pd.DataFrame(
        {
            ("AAPL", "Close"): [100.0, 102.0],
            ("AAPL", "Volume"): [1000, 1200],
            ("MSFT", "Close"): [200.0, 201.0],
        },
        index=pd.to_datetime(["2026-05-18", "2026-05-19"]),
    )

    frame = _single_symbol_price_frame(data, "AAPL")

    assert list(frame["fecha"]) == ["2026-05-18", "2026-05-19"]
    assert list(frame["close"]) == [100.0, 102.0]
    assert list(frame["volume"]) == [1000, 1200]


def test_position_evolution_summary_calculates_entry_and_level_distances():
    frame = pd.DataFrame(
        [
            {"fecha": "2026-05-18", "close": 100.0, "volume": 1000},
            {"fecha": "2026-05-19", "close": 110.0, "volume": 1200},
        ]
    )

    summary = _position_evolution_summary(
        frame,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=120.0,
    )

    assert summary["bars"] == 2
    assert summary["last_price"] == 110.0
    assert summary["return_from_entry"] == 0.1
    assert summary["distance_to_stop"] == 0.136364
    assert summary["distance_to_take"] == 0.090909


def test_latest_daily_equity_change_prefers_alpaca_daily_delta():
    payload = {
        "timestamp": [
            "2026-05-22T00:00:00Z",
            "2026-05-23T00:00:00Z",
            "2026-05-26T00:00:00Z",
        ],
        "equity": [70719.88, 71081.25, 71072.78],
    }

    change = _latest_daily_equity_change(history={}, current_equity=None, portfolio_history=payload)

    assert change["equity"] == 71072.78
    assert change["pl"] == -8.47
    assert change["pl_pct"] == -0.000119
    assert change["source"] == "Alpaca"


def test_latest_daily_equity_change_falls_back_to_estimated_series():
    history = {
        "days": [
            {"date": "2026-05-25", "realized_pl": 10.0, "open_unrealized_pl": 0.0, "buy_notional": 1000.0},
            {"date": "2026-05-26", "realized_pl": -5.0, "open_unrealized_pl": 0.0, "sell_notional": 500.0},
        ]
    }

    change = _latest_daily_equity_change(history=history, current_equity=1005.0, portfolio_history={})

    assert change["equity"] == 1005.0
    assert change["pl"] == -5.0
    assert change["pl_pct"] == -0.00495
    assert change["source"] == "estimado"


def test_sidebar_version_label_uses_semantic_version():
    assert _sidebar_version_label() == f"v{__version__}"


def test_local_datetime_renders_spain_dst_from_utc():
    assert _local_datetime("2026-05-29T18:00:00+00:00", "Europe/Madrid") == "2026-05-29 20:00:00"


def test_eventing_format_time_treats_naive_timestamps_as_utc():
    assert _format_time("2026-05-29T18:00:00", "Europe/Madrid") == "20:00:00"


def test_next_opportunity_snapshot_run_text_same_day():
    settings = Settings(OPPORTUNITY_SNAPSHOT_TIMES_LOCAL="16:00,19:00,21:00", LOCAL_TIMEZONE="Europe/Madrid")

    result = _next_opportunity_snapshot_run_text(
        settings,
        now_local=datetime.fromisoformat("2026-05-28T18:15:00+02:00"),
    )

    assert result == "2026-05-28 19:00"


def test_next_opportunity_snapshot_run_text_next_day_after_last_slot():
    settings = Settings(OPPORTUNITY_SNAPSHOT_TIMES_LOCAL="16:00,19:00,21:00", LOCAL_TIMEZONE="Europe/Madrid")

    result = _next_opportunity_snapshot_run_text(
        settings,
        now_local=datetime.fromisoformat("2026-05-28T21:15:00+02:00"),
    )

    assert result == "2026-05-29 16:00"


def test_ci_task_activity_groups_messages_by_initiative_event():
    tasks = [
        {
            "task_id": "task_market",
            "event_id": "evt_1",
            "agent_name": "MarketEstimatorAgent",
            "status": "COMPLETED",
            "payload": {"focus": "market_regime"},
        },
        {
            "task_id": "task_strategy",
            "event_id": "evt_1",
            "agent_name": "StrategyEvaluatorAgent",
            "status": "RUNNING",
            "payload": {"focus": "strategy_validation"},
        },
    ]
    events = [
        {
            "event_id": "raw_1",
            "cycle_id": "ci_cycle_test",
            "agent": "MarketEstimatorAgent",
            "event_type": "lab_task_completed",
            "payload_json": '{"task_id":"task_market","event_id":"evt_1","summary":"mercado listo"}',
            "created_at": "2026-05-29T18:00:00+00:00",
        },
        {
            "event_id": "raw_2",
            "cycle_id": "ci_cycle_test",
            "agent": "StrategyEvaluatorAgent",
            "event_type": "lab_task_started",
            "payload_json": '{"task_id":"task_strategy","event_id":"evt_1","focus":"strategy_validation"}',
            "created_at": "2026-05-29T18:01:00+00:00",
        },
    ]

    grouped = _ci_task_activity(events, tasks, cycle_id="ci_cycle_test")

    assert len(grouped) == 1
    assert grouped[0]["initiative_id"] == "evt_1"
    assert set(grouped[0]["agent_names"]) == {"MarketEstimatorAgent", "StrategyEvaluatorAgent"}
    assert len(grouped[0]["messages"]) == 2


def test_ci_conversation_groups_builds_full_thread_per_initiative():
    initiatives = [
        {
            "initiative_id": "ci_init_1",
            "initiative_key": "software:runtime_reliability",
            "title": "Reforzar fiabilidad del runtime",
            "status": "ANALYZING",
            "owner_agent": "SoftwareReliabilityAgent",
            "target_metric": "runtime_error_rate",
            "risk_level": "LOW",
            "latest_decision": {"decision": "OPEN"},
            "next_action": "Esperar respuesta de agentes.",
            "linked_event_ids": ["ci_event_1"],
            "created_at": "2026-06-03T18:00:00+00:00",
            "updated_at": "2026-06-03T18:04:00+00:00",
        }
    ]
    initiative_messages = [
        {
            "initiative_id": "ci_init_1",
            "cycle_id": "ci_cycle_test",
            "agent_name": "SoftwareReliabilityAgent",
            "message_type": "task_completed",
            "content": {"summary": "Se detecta deuda tecnica en el manejo de reintentos."},
            "created_at": "2026-06-03T18:03:00+00:00",
        },
        {
            "initiative_id": "ci_init_1",
            "cycle_id": "ci_cycle_test",
            "agent_name": "ValidationAgent",
            "message_type": "validation_recorded",
            "content": {"validation": {"status": "PASSED", "proposal_id": "prop_1"}},
            "created_at": "2026-06-03T18:04:00+00:00",
        },
    ]
    recent_agent_events = [
        {
            "cycle_id": "ci_cycle_test",
            "agent": "OrchestratorAgent",
            "event_type": "lab_event_planned",
            "payload_json": '{"event_id":"ci_event_1","event_type":"manual_trigger"}',
            "created_at": "2026-06-03T18:01:00+00:00",
        }
    ]

    grouped = _ci_conversation_groups(
        initiatives,
        initiative_messages,
        recent_agent_events,
        task_groups=[],
        proposals=[],
        validations=[],
        cycle_id="ci_cycle_test",
    )

    assert len(grouped) == 1
    assert grouped[0]["title"] == "Reforzar fiabilidad del runtime"
    assert [item["stage"] for item in grouped[0]["messages"]] == [
        "Propuesta del orquestador",
        "Evento planificado",
        "Respuesta del agente",
        "Resultado de validacion",
    ]
    assert grouped[0]["messages"][2]["body"] == "Se detecta deuda tecnica en el manejo de reintentos."
    assert grouped[0]["messages"][3]["body"] == "Validacion PASSED para prop_1."
    assert grouped[0]["last_message_at"] == "2026-06-03T18:04:00+00:00"
    assert "1 respuesta de agente" in grouped[0]["rollup"]["done"]
    assert "1 validacion" in grouped[0]["rollup"]["done"]
    assert grouped[0]["rollup"]["remaining"] == "Esperar respuesta de agentes."
    assert grouped[0]["rollup"]["why"].startswith(
        "Ya hay trabajo de agentes, pero la iniciativa sigue abierta y aun no ha cerrado su siguiente decision."
    )


def test_ci_conversation_groups_includes_linked_proposals_and_validations():
    initiatives = [
        {
            "initiative_id": "ci_init_1",
            "initiative_key": "software:error_investigation",
            "title": "Error Investigation",
            "status": "VALIDATING",
            "owner_agent": "OrchestratorAgent",
            "target_metric": "monitoring_change",
            "risk_level": "LOW",
            "latest_decision": {"decision": "PENDING"},
            "next_action": "Esperar validacion objetiva.",
            "linked_proposal_ids": ["prop_1"],
            "linked_validation_ids": ["val_1"],
            "created_at": "2026-06-03T18:00:00+00:00",
            "updated_at": "2026-06-03T18:04:00+00:00",
        }
    ]

    grouped = _ci_conversation_groups(
        initiatives,
        initiative_messages=[],
        recent_agent_events=[],
        task_groups=[],
        proposals=[
            {
                "proposal_id": "prop_1",
                "target_identifier": "error_investigation",
                "created_at": "2026-06-03T18:01:00+00:00",
                "payload": {
                    "proposed_value": "Investigar errores recientes para prevenir recurrencias.",
                    "expected_impact": "Reducir tiempo medio de resolucion.",
                },
            }
        ],
        validations=[
            {
                "validation_id": "val_1",
                "proposal_id": "prop_1",
                "status": "PENDING",
                "created_at": "2026-06-03T18:02:00+00:00",
                "payload": {
                    "objective_summary": "La propuesta dispone de evidencia operativa suficiente para revision.",
                },
            }
        ],
        cycle_id="ci_cycle_test",
    )

    assert [item["stage"] for item in grouped[0]["messages"]] == [
        "Propuesta del orquestador",
        "Propuesta consolidada",
        "Resultado de validacion",
    ]
    assert grouped[0]["messages"][1]["body"] == "Investigar errores recientes para prevenir recurrencias."
    assert grouped[0]["messages"][2]["body"] == "La propuesta dispone de evidencia operativa suficiente para revision."
    assert grouped[0]["last_message_at"] == "2026-06-03T18:02:00+00:00"
    assert "1 propuesta" in grouped[0]["rollup"]["done"]
    assert "1 validacion" in grouped[0]["rollup"]["done"]
    assert "Validando evidencia" in grouped[0]["rollup"]["now"]
    assert grouped[0]["rollup"]["why"].startswith(
        "La iniciativa sigue en fase de validacion y no ha cerrado en READY_TO_APPLY o REJECTED."
    )


def test_ci_conversation_groups_infers_validation_from_linked_proposal():
    initiatives = [
        {
            "initiative_id": "ci_init_1",
            "initiative_key": "software:continuous_improvement",
            "title": "Continuous Improvement",
            "status": "VALIDATING",
            "owner_agent": "OrchestratorAgent",
            "target_metric": "monitoring_change",
            "risk_level": "LOW",
            "latest_decision": {"decision": "PENDING"},
            "next_action": "Revalidar y cerrar.",
            "linked_proposal_ids": ["prop_1"],
            "linked_validation_ids": [],
            "created_at": "2026-06-01T18:00:00+00:00",
            "updated_at": "2026-06-08T18:00:00+00:00",
        }
    ]

    grouped = _ci_conversation_groups(
        initiatives,
        initiative_messages=[],
        recent_agent_events=[],
        task_groups=[],
        proposals=[
            {
                "proposal_id": "prop_1",
                "target_identifier": "continuous_improvement",
                "created_at": "2026-06-01T18:01:00+00:00",
                "payload": {"proposed_value": "Crear validaciones adicionales."},
            }
        ],
        validations=[
            {
                "validation_id": "val_1",
                "proposal_id": "prop_1",
                "status": "PASSED",
                "created_at": "2026-06-01T18:02:00+00:00",
                "payload": {"objective_summary": "Validacion objetiva superada."},
            }
        ],
        cycle_id="ci_cycle_test",
    )

    assert [item["stage"] for item in grouped[0]["messages"]] == [
        "Propuesta del orquestador",
        "Propuesta consolidada",
        "Resultado de validacion",
    ]
    assert "1 validacion" in grouped[0]["rollup"]["done"]
    assert grouped[0]["rollup"]["why"].startswith(
        "La iniciativa sigue en fase de validacion y no ha cerrado en READY_TO_APPLY o REJECTED."
    )


def test_ci_runtime_alert_exposes_error_and_retry():
    alert = _ci_runtime_alert(
        {
            "status": "FAILED",
            "payload": {
                "error": "timeout talking to LLM",
                "retry_attempt": 2,
                "next_retry_at": "2026-06-02T16:20:44+00:00",
            },
        },
        {
            "status": "failed",
            "detail": "timeout talking to LLM",
            "extra": {},
        },
    )

    assert alert is not None
    assert "timeout talking to LLM" in alert["message"]
    assert "Intento acumulado: 2" in alert["message"]


def test_ci_global_export_payload_groups_history_for_deepresearch():
    dataset = {
        "cycles": [{"cycle_id": "ci_cycle_1"}],
        "initiatives": [
            {"initiative_id": "init_1", "status": "ANALYZING"},
            {"initiative_id": "init_2", "status": "CLOSED"},
        ],
        "conversation_groups": [{"group_id": "init_1", "messages": [{"body": "Analisis"}]}],
        "proposals": [
            {"proposal_id": "prop_1", "status": "PENDING"},
            {"proposal_id": "prop_2", "status": "REJECTED"},
        ],
        "validations": [{"validation_id": "val_1", "status": "PASSED"}],
        "decisions": [{"decision_id": "dec_1", "decision": "REJECTED"}],
        "tasks": [
            {"task_id": "task_1", "status": "DISCOVERED"},
            {"task_id": "task_2", "status": "COMPLETED"},
        ],
        "events": [
            {"event_id": "event_1", "status": "DISCOVERED"},
            {"event_id": "event_2", "status": "COMPLETED"},
        ],
        "hypotheses": [{"hypothesis_id": "hyp_1"}],
        "experiments": [{"experiment_id": "exp_1"}],
        "applied_changes": [{"applied_change_id": "chg_1"}],
        "llm_responses": [{"llm_call_id": "llm_1"}],
        "agent_events": [],
        "initiative_messages": [],
        "memories": [],
    }

    payload = _ci_global_export_payload(
        dataset,
        generated_at="2026-06-07T00:00:00+00:00",
        limit=10000,
    )

    assert payload["schema"] == "agente_bolsa.continuous_improvement.deepresearch.all_history.v1"
    assert payload["intended_consumer"] == "LLM/deepresearch"
    assert payload["summary"]["cycles"] == 1
    assert payload["summary"]["conversation_threads"] == 1
    assert payload["summary"]["pending_or_applicable_proposals"] == 1
    assert payload["summary"]["studied_proposals"] == 1
    assert payload["summary"]["pending_tasks"] == 1
    assert payload["summary"]["open_events"] == 1
    assert payload["pending"]["proposals"][0]["proposal_id"] == "prop_1"
    assert payload["studied"]["proposals"][0]["proposal_id"] == "prop_2"
    assert payload["raw_collections"]["llm_responses"][0]["llm_call_id"] == "llm_1"


def _opportunity_candidate(symbol: str, **overrides):
    candidate = {
        "symbol": symbol,
        "direction": "long",
        "score": 15.0,
        "selection_score": 0.05,
        "rank_priority_score": 0.03,
        "selection_rank": 1,
        "setup_name": "orderly_breakout",
        "setup_quality": "strong",
        "reasons": ["momentum 20d positivo", "volumen confirma subida"],
        "technical_state": {
            "close": 105.0,
            "return_5d": 0.04,
            "return_20d": 0.12,
            "return_60d": 0.18,
            "sma_20": 100.0,
            "sma_50": 95.0,
            "sma_200": 80.0,
            "rsi_14": 64.0,
            "atr_14": 3.5,
            "volume_zscore_20": 1.6,
            "breakout_failure_risk": False,
            "candle_patterns": ["bullish_engulfing"],
            "chart_patterns": [{"label": "Bull flag", "pattern": "flag"}],
        },
        "risk_plan": {
            "entry_price": 105.0,
            "stop_loss": 99.0,
            "take_profit": 117.0,
            "reward_risk": 2.0,
            "invalidation": "Pierde soporte dinamico.",
            "time_stop": "5-10 sesiones",
        },
    }
    candidate.update(overrides)
    return candidate


def _portfolio_snapshot(*, positions=None, open_orders=None, buying_power=10000.0, portfolio_value=20000.0):
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=buying_power,
        portfolio_value=portfolio_value,
        buying_power=buying_power,
        positions=positions or [],
        open_orders=open_orders or [],
    )


def test_opportunity_candidates_deduplicates_filters_long_and_limits():
    repeated = _opportunity_candidate("AAPL", selection_score=0.07)
    context = {
        "selected_candidates": [repeated],
        "top_longs": [_opportunity_candidate("AAPL", selection_score=0.04)],
        "all_candidates": [
            _opportunity_candidate(f"SYM{i:02d}", selection_score=0.06 - (i * 0.001))
            for i in range(25)
        ] + [
            _opportunity_candidate("TSLA", direction="short", selection_score=0.99),
        ],
    }

    result = _opportunity_candidates(context, limit=20)

    assert len(result) == 20
    assert result[0]["symbol"] == "AAPL"
    assert len([item for item in result if item["symbol"] == "AAPL"]) == 1
    assert all(item["direction"] == "long" for item in result)


def test_opportunity_candidates_sort_uses_fallbacks():
    strongest_selection = _opportunity_candidate("AAA", selection_score=0.08, rank_priority_score=0.01, score=10)
    strongest_priority = _opportunity_candidate("BBB", selection_score=None, rank_priority_score=0.07, score=18)
    strongest_score = _opportunity_candidate("CCC", selection_score=None, rank_priority_score=None, score=22)

    result = _opportunity_candidates(
        {"selected_candidates": [strongest_score, strongest_priority, strongest_selection]},
        limit=20,
    )

    assert [item["symbol"] for item in result] == ["AAA", "BBB", "CCC"]


def test_opportunity_risk_plan_extracts_values_and_fallbacks():
    candidate = _opportunity_candidate("NVDA")

    risk = _opportunity_risk_plan(candidate)

    assert risk["current_price"] == 105.0
    assert risk["entry_price"] == 105.0
    assert risk["stop_loss"] == 99.0
    assert risk["take_profit"] == 117.0
    assert risk["reward_risk"] == 2.0


def test_opportunity_status_reports_pending_plan():
    candidate = _opportunity_candidate("AAPL")
    status = _opportunity_status(
        candidate,
        portfolio=_portfolio_snapshot(),
        pending_plans_by_symbol={"AAPL": {"plan_id": "plan_1"}},
        settings=Settings(),
        llm_context=None,
    )

    assert status["label"] == "Plan pendiente"


def test_opportunity_status_reports_open_order():
    candidate = _opportunity_candidate("AAPL")
    portfolio = _portfolio_snapshot(open_orders=[OrderSnapshot("ord_1", "AAPL", "buy", 1.0, None, "market", "new")])

    status = _opportunity_status(
        candidate,
        portfolio=portfolio,
        pending_plans_by_symbol={},
        settings=Settings(),
        llm_context=None,
    )

    assert status["label"] == "Orden abierta"


def test_opportunity_status_reports_existing_position():
    candidate = _opportunity_candidate("AAPL")
    portfolio = _portfolio_snapshot(
        positions=[PositionSnapshot("AAPL", 2.0, 210.0, 100.0, 105.0, 10.0, 0.05)],
    )

    status = _opportunity_status(
        candidate,
        portfolio=portfolio,
        pending_plans_by_symbol={},
        settings=Settings(),
        llm_context=None,
    )

    assert status["label"] == "Posicion abierta"


def test_opportunity_status_reports_blocked_auto_buy():
    candidate = _opportunity_candidate("AAPL", blocked_auto_buy=True, blocked_auto_buy_reason="shadow_only")

    status = _opportunity_status(
        candidate,
        portfolio=_portfolio_snapshot(),
        pending_plans_by_symbol={},
        settings=Settings(AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False),
        llm_context=None,
    )

    assert status["label"] == "Bloqueada auto-compra"
    assert "shadow_only" in status["reason"]


def test_opportunity_status_uses_llm_context_when_available():
    candidate = _opportunity_candidate("AAPL")
    llm_context = {
        "decision": "hold",
        "explanation": "El LLM ve setup correcto pero aun no confirma entrada.",
        "approved_buy": False,
    }

    status = _opportunity_status(
        candidate,
        portfolio=_portfolio_snapshot(),
        pending_plans_by_symbol={},
        settings=Settings(AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False),
        llm_context=llm_context,
    )

    assert status["label"] == "LLM hold"
    assert "aun no confirma entrada" in status["reason"]


def test_llm_status_reason_marks_approved_buy():
    tone, label, reason = _llm_status_reason(
        {"decision": "buy", "approved_buy": True, "explanation": "Aprobada por momentum y riesgo controlado."}
    )

    assert tone == "good"
    assert label == "LLM aprobo compra"
    assert "momentum" in reason


def test_latest_llm_context_by_symbol_prefers_learning_observations(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.upsert_learning_observation(
        {
            "observation_id": "obs_1",
            "signal_date": "2026-05-27",
            "symbol": "AAPL",
            "source_family": "closed_market_study",
            "best_signal_id": "sig_1",
            "best_score": 17.0,
            "decision": "hold",
            "explanation": "El LLM espera confirmacion adicional antes de comprar.",
            "llm_considered": True,
            "approved_buy": False,
            "blocked_entry_quality": True,
            "blocked_backtest": False,
            "executed_buy": False,
            "gate": {"llm": {"reason": "setup valido pero entrada aun floja"}},
            "features": {},
            "outcome": {},
            "execution": {},
            "rank_path": [],
        }
    )

    context = _latest_llm_context_by_symbol(store, ["AAPL"])

    assert context["AAPL"]["source"] == "learning_observations"
    assert context["AAPL"]["decision"] == "hold"
    assert context["AAPL"]["blocked_entry_quality"] is True
    assert "confirmacion adicional" in context["AAPL"]["explanation"]


def test_manual_opportunity_recommendation_keeps_valid_stop_take():
    candidate = _opportunity_candidate("MSFT")
    recommendation = _manual_opportunity_recommendation(candidate, Settings())

    assert recommendation.symbol == "MSFT"
    assert recommendation.action == "buy"
    assert recommendation.entry_price == 105.0
    assert recommendation.stop_loss == 99.0
    assert recommendation.take_profit == 117.0
    assert recommendation.source == "manual_opportunity_screen"


def _company_signal(symbol="AAPL", run_id="run_1", *, signal_id=None, close=101.0, entry_price=100.0, score=12):
    return {
        "signal_id": signal_id or f"{run_id}:{symbol}",
        "source_run_id": run_id,
        "source": "intraday_scan",
        "symbol": symbol,
        "signal_date": "2026-06-05",
        "decision": "candidate",
        "features": {
            "close": close,
            "entry_price": entry_price,
            "score": score,
            "direction": "long",
            "reasons": ["precio sobre SMA200"],
        },
        "gate": {},
        "outcome": {},
        "created_at": "2026-06-05T19:00:00+00:00",
        "updated_at": "2026-06-05T19:00:00+00:00",
    }


def test_company_study_symbol_summary_groups_latest_and_price():
    rows = [
        _company_signal("AAPL", "run_1", close=101.0, score=10),
        _company_signal("AAPL", "run_2", close=110.0, score=14),
        _company_signal("MSFT", "run_3", close=220.0, score=9),
    ]
    rows[1]["created_at"] = "2026-06-05T20:00:00+00:00"

    summary = _company_study_symbol_summary(rows)
    by_symbol = {item["simbolo"]: item for item in summary}

    assert by_symbol["AAPL"]["iteraciones"] == 2
    assert by_symbol["AAPL"]["ultimo_precio"] == 110.0
    assert by_symbol["AAPL"]["ultimo_score"] == 14
    assert by_symbol["MSFT"]["iteraciones"] == 1


def test_company_study_reason_priority_learning_over_recommendation_and_plan():
    signal = _company_signal("AAPL", "run_1", signal_id="sig_1")
    learning = {
        "sig_1": {
            "decision": "hold",
            "explanation": "Bloqueada por entrada extendida.",
            "approved_buy": False,
            "blocked_entry_quality": True,
            "blocked_backtest": False,
            "executed_buy": False,
        }
    }
    recommendations = {
        ("run_1", "AAPL"): {
            "action": "buy",
            "payload_json": '{"reason":"LLM compra"}',
        }
    }
    plans = {
        ("run_1", "AAPL"): {
            "approved": 1,
            "payload_json": '{"risk_decision":{"reason":"riesgo ok"}}',
        }
    }

    reason = _company_study_reason(signal, learning, recommendations, plans)

    assert reason["source"] == "learning_observations"
    assert reason["label"] == "No compra: calidad"
    assert "extendida" in reason["reason"]


def test_company_study_reason_reports_approved_buy_and_backtest_block():
    signal = _company_signal("AAPL", "run_1", signal_id="sig_1")

    approved = _company_study_reason(
        signal,
        {
            "sig_1": {
                "decision": "buy",
                "explanation": "Compra aprobada por momentum.",
                "approved_buy": True,
                "blocked_entry_quality": False,
                "blocked_backtest": False,
                "executed_buy": False,
            }
        },
        {},
        {},
    )
    blocked = _company_study_reason(
        signal,
        {
            "sig_1": {
                "decision": "hold",
                "explanation": "Backtest insuficiente.",
                "approved_buy": False,
                "blocked_entry_quality": False,
                "blocked_backtest": True,
                "executed_buy": False,
            }
        },
        {},
        {},
    )

    assert approved["label"] == "Compra aprobada"
    assert approved["tone"] == "good"
    assert blocked["label"] == "No compra: backtest"
    assert blocked["tone"] == "bad"


def test_company_study_reason_fallback_candidate():
    reason = _company_study_reason(_company_signal("AAPL"), {}, {}, {})

    assert reason["source"] == "fallback"
    assert "Candidato tecnico" in reason["label"]
    assert "no llego a compra" in reason["reason"]


def test_study_price_prefers_close_and_falls_back_to_entry():
    assert _study_price({"close": 10.0, "entry_price": 9.5}) == 10.0
    assert _study_price({"entry_price": 9.5}) == 9.5
    assert _study_price({}) is None


def test_company_study_news_loads_symbol_and_excludes_manifest(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "news_sentiment_run_1.manifest.json").write_text("{}", encoding="utf-8")
    (reports / "news_sentiment_run_1.json").write_text(
        """
        {
          "run_id": "run_1",
          "as_of": "2026-06-05T20:00:00+00:00",
          "results": [
            {
              "symbol": "AAPL",
              "news": [{"title": "Apple headline"}],
              "sentiment": {"sentiment": "positive", "sentiment_score": 1},
              "material_risk": {"material": false}
            },
            {"symbol": "MSFT", "news": []}
          ]
        }
        """,
        encoding="utf-8",
    )

    files = _company_study_news_files(reports)
    news = _company_study_news_for_symbol(reports, "AAPL", "run_1")

    assert [path.name for path in files] == ["news_sentiment_run_1.json"]
    assert len(news) == 1
    assert news[0]["symbol"] == "AAPL"
    assert news[0]["run_id"] == "run_1"


def test_latest_analyzed_news_flattens_and_limits_reports(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "news_sentiment_run_1.manifest.json").write_text("{}", encoding="utf-8")
    (reports / "news_sentiment_run_1.json").write_text(
        """
        {
          "run_id": "run_1",
          "as_of": "2026-06-05T20:00:00+00:00",
          "results": [
            {
              "symbol": "AAPL",
              "news": [
                {
                  "title": "Apple headline",
                  "publisher": "Example",
                  "published_at": "2026-06-05T19:00:00+00:00",
                  "link": "https://example.com/aapl"
                },
                {
                  "title": "Older headline",
                  "publisher": "Example",
                  "published_at": "2026-06-04T19:00:00+00:00"
                }
              ],
              "sentiment": {"sentiment": "positive", "sentiment_score": 1},
              "material_risk": {"severity": "none"}
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    rows = _latest_analyzed_news(reports, limit=1)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["title"] == "Apple headline"
    assert rows[0]["sentiment"] == "positive"


def test_company_study_export_payload_is_llm_ready():
    signal = _company_signal("AAPL", "run_1", signal_id="sig_1", close=123.45, score=15)
    reason = {
        "source": "learning_observations",
        "label": "Compra aprobada",
        "reason": "Momentum confirmado con riesgo controlado.",
        "tone": "good",
        "payload": {"approved_buy": True},
    }
    news = [
        {
            "symbol": "AAPL",
            "run_id": "run_1",
            "sentiment": {"sentiment": "positive", "sentiment_score": 1},
            "news": [{"title": "Apple headline"}],
        }
    ]

    payload = _company_study_export_payload(
        symbol="AAPL",
        signals=[signal],
        reasons=[reason],
        symbol_news=news,
        filters={"since_date": "2026-06-01", "sources": ["intraday_scan"]},
        generated_at="2026-06-07T00:00:00+00:00",
    )

    assert payload["schema"] == "agente_bolsa.company_studies.deepresearch.v1"
    assert payload["intended_consumer"] == "LLM/deepresearch"
    assert payload["summary"]["iterations"] == 1
    assert payload["summary"]["approved_or_bought"] == 1
    assert payload["summary"]["latest_price"] == 123.45
    assert payload["iterations"][0]["price"] == 123.45
    assert payload["iterations"][0]["decision_reason"]["reason"].startswith("Momentum confirmado")
    assert payload["iterations"][0]["news_sentiment"][0]["news"][0]["title"] == "Apple headline"


def test_company_study_global_export_payload_groups_all_companies():
    aapl = _company_signal("AAPL", "run_1", signal_id="sig_aapl", close=123.45, score=15)
    msft = _company_signal("MSFT", "run_2", signal_id="sig_msft", close=250.0, score=9)
    context = {
        "learning_by_signal": {
            "sig_aapl": {
                "decision": "buy",
                "explanation": "Compra aprobada por momentum.",
                "approved_buy": True,
                "blocked_entry_quality": False,
                "blocked_backtest": False,
                "executed_buy": False,
            },
            "sig_msft": {
                "decision": "hold",
                "explanation": "Backtest insuficiente.",
                "approved_buy": False,
                "blocked_entry_quality": False,
                "blocked_backtest": True,
                "executed_buy": False,
            },
        },
        "recommendations_by_cycle_symbol": {},
        "plans_by_cycle_symbol": {},
    }
    payload = _company_study_global_export_payload(
        signals=[aapl, msft],
        context=context,
        news_by_symbol={"AAPL": [{"symbol": "AAPL", "run_id": "run_1", "news": [{"title": "AAPL news"}]}]},
        filters={"since_date": "2026-06-01"},
        generated_at="2026-06-07T00:00:00+00:00",
    )

    assert payload["schema"] == "agente_bolsa.company_studies.deepresearch.all_companies.v1"
    assert payload["summary"]["companies"] == 2
    assert payload["summary"]["iterations"] == 2
    assert payload["summary"]["approved_or_bought"] == 1
    assert payload["summary"]["blocked"] == 1
    assert [item["symbol"] for item in payload["companies"]] == ["AAPL", "MSFT"]
    assert payload["companies"][0]["iterations"][0]["news_sentiment"][0]["news"][0]["title"] == "AAPL news"


def test_company_study_decision_context_chunks_large_signal_id_lists(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    signals = []
    for index in range(1200):
        symbol = f"S{index:04d}"
        signal_id = f"run_1:{symbol}"
        store.save_signal_outcome(
            signal_id=signal_id,
            source_run_id="run_1",
            source="intraday_scan",
            symbol=symbol,
            signal_date="2026-06-05",
            decision="candidate",
            features={"close": 100.0 + index},
        )
        signals.append(_company_signal(symbol, "run_1", signal_id=signal_id))
    store.upsert_learning_observation(
        {
            "observation_id": "obs_large",
            "signal_date": "2026-06-05",
            "symbol": "S1199",
            "source_family": "intraday_scan",
            "best_signal_id": "run_1:S1199",
            "best_score": 10.0,
            "decision": "hold",
            "explanation": "Encontrada pese a lista grande.",
            "llm_considered": True,
            "approved_buy": False,
            "blocked_entry_quality": False,
            "blocked_backtest": True,
            "executed_buy": False,
            "gate": {},
            "features": {},
            "outcome": {},
            "execution": {},
            "rank_path": [],
        }
    )

    context = _company_study_decision_context(store, signals)

    assert context["learning_by_signal"]["run_1:S1199"]["blocked_backtest"] is True


def test_company_study_signal_rows_uses_sqlite_index_without_report_json(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="run_1:AAPL",
        source_run_id="run_1",
        source="intraday_scan",
        symbol="AAPL",
        signal_date="2026-06-05",
        decision="candidate",
        features={"close": 101.0, "score": 12},
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "closed_market_technical_study_run_1.json").write_text("not json", encoding="utf-8")

    rows = _company_study_signal_rows(store, since_date="2026-06-01", sources=["intraday_scan"])

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["features"]["close"] == 101.0


def test_create_manual_opportunity_plan_saves_pending_plan(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        AUTO_PAPER_TRADING=False,
        REQUIRE_HUMAN_APPROVAL=True,
        MAX_POSITION_EXPOSURE=0.10,
        MAX_PORTFOLIO_EXPOSURE=0.80,
        MIN_ORDER_NOTIONAL=100.0,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    candidate = _opportunity_candidate("AAPL")
    portfolio = _portfolio_snapshot(buying_power=5000.0, portfolio_value=20000.0)

    result = _create_manual_opportunity_plan(
        candidate=candidate,
        settings=settings,
        store=store,
        portfolio=portfolio,
    )

    assert result["ok"] is True
    pending = store.pending_order_plans(limit=20)
    assert len(pending) == 1
    assert pending[0]["symbol"] == "AAPL"
    assert pending[0]["plan_id"] == result["plan_id"]
