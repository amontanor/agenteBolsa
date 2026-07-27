from __future__ import annotations

from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import _auto_paper_trade
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.tools.market_cycle_timing import MarketCycleTiming


class _StoreSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.plans: list[dict] = []
        self.rec_payloads: list[dict] = []
        self.plan_payloads: list[dict] = []
        self.broker_payloads: list[dict] = []

    def save_trade_recommendation(self, **kwargs) -> None:
        self.calls.append("save_trade_recommendation")
        self.rec_payloads.append(dict(kwargs))

    def save_order_plan(self, **kwargs) -> None:
        self.calls.append("save_order_plan")
        self.plans.append({**kwargs, "status": "PENDING"})
        self.plan_payloads.append(dict(kwargs))

    def pending_order_plans(self, **_kwargs):
        return self.plans

    def save_broker_order(self, **kwargs) -> None:
        self.calls.append("save_broker_order")
        self.broker_payloads.append(dict(kwargs))

    def count_broker_orders(self, **_kwargs) -> int:
        return 0


class _Reporter:
    def emit(self, *_args, **_kwargs) -> None:
        pass


def _patch_trading_flow(monkeypatch, *, shadow: bool = False, fail_backtest: bool = False,
                       llm_selected: bool | None = None):
    import agente_bolsa.cycle_runner as runner

    calls: list[str] = []
    rec_kwargs = {"symbol": "AAPL", "action": "buy", "confidence": 0.9, "reason": "prueba",
                  "entry_price": 100, "stop_loss": 95, "take_profit": 110}
    if llm_selected is not None:
        rec_kwargs["llm_selected"] = llm_selected
    recommendation = TradeRecommendation(**rec_kwargs)
    plan = OrderPlan("AAPL", "buy", 100.0, 1.0, 100.0, 95.0, 110.0, recommendation, RiskDecision(True, "ok", {}))

    monkeypatch.setattr(runner, "active_learning_mode", lambda _settings: {"shadow_first": True, "shadow_strategies": []} if shadow else None)
    monkeypatch.setattr(runner, "load_daily_learning_context", lambda _path: {})
    monkeypatch.setattr(runner, "load_operational_response_context", lambda _path: {})
    monkeypatch.setattr(runner, "load_operational_block_context", lambda _path: {})
    monkeypatch.setattr(runner, "record_setup_edge_cycle_shadow", lambda *_args: {})
    monkeypatch.setattr(runner, "MarketCalendar", lambda *_args: SimpleNamespace(status=lambda: SimpleNamespace(is_open=True)))
    monkeypatch.setattr(runner, "BrokerClientFactory", lambda _settings: SimpleNamespace(alpaca_portfolio_snapshot=lambda: {}))
    monkeypatch.setattr(runner, "build_portfolio_rebalance_context", lambda *_args: {})
    monkeypatch.setattr(runner, "load_latest_sentiment", lambda _path: {})
    monkeypatch.setattr(runner, "augment_recommendations_with_deterministic_fallback", lambda _settings, _portfolio, _context, items, **_kwargs: (items, {"added": []}))
    monkeypatch.setattr(runner, "request_trade_recommendations", lambda *_args: calls.append("request_trade_recommendations") or {"recommendations": [recommendation]})
    monkeypatch.setattr(runner, "review_recommendations", lambda *_args: (calls.append("review_recommendations") or [recommendation], [{"symbol": "AAPL", "action": "buy", "approved": True}]))
    monkeypatch.setattr(runner, "review_recommendations_adversarial", lambda *_args, **_kwargs: calls.append("review_recommendations_adversarial") or [{"symbol": "AAPL", "action": "buy", "approved": True}])
    monkeypatch.setattr(runner, "_annotate_recommendations_with_strategy", lambda items, *_args: items)
    monkeypatch.setattr(runner, "_annotate_recommendations_with_lineage", lambda items, *_args, **_kwargs: items)
    monkeypatch.setattr(runner, "recommendation_input_fingerprint", lambda *_args, **_kwargs: "fingerprint")
    monkeypatch.setattr(runner, "_apply_entry_quality_gate", lambda *_args, **_kwargs: (calls.append("_apply_entry_quality_gate") or [recommendation], []))

    def backtest(*_args):
        calls.append("_apply_backtest_gate")
        if fail_backtest:
            raise RuntimeError("backtest failed")
        return [recommendation], []

    monkeypatch.setattr(runner, "_apply_backtest_gate", backtest)
    monkeypatch.setattr(runner, "update_signal_decisions", lambda *_args, **_kwargs: calls.append("update_signal_decisions") or 0)
    monkeypatch.setattr(runner, "build_order_plans", lambda *_args, **_kwargs: calls.append("build_order_plans") or [plan])
    monkeypatch.setattr(runner, "_apply_daily_buy_limit", lambda *_args, **_kwargs: calls.append("_apply_daily_buy_limit") or _args[4])
    monkeypatch.setattr(runner, "_apply_low_sample_daily_quota", lambda *_args, **_kwargs: calls.append("_apply_low_sample_daily_quota") or _args[4])
    monkeypatch.setattr(runner, "_separate_strategy_paused_plans", lambda _mode, plans: (calls.append("_separate_strategy_paused_plans") or plans, []))
    monkeypatch.setattr(runner, "_effective_buy_plan_limit", lambda *_args: 1)
    monkeypatch.setattr(runner, "_effective_daily_buy_limit", lambda *_args: 1)
    monkeypatch.setattr(runner, "_low_sample_usage_payload", lambda *_args: {})
    monkeypatch.setattr(runner, "update_signal_execution_status", lambda *_args, **_kwargs: calls.append("update_signal_execution_status") or 1)
    monkeypatch.setattr(runner, "submit_paper_order_plan", lambda *_args, **_kwargs: calls.append("submit_paper_order_plan") or {"id": "broker-1", "status": "accepted"})
    monkeypatch.setattr(runner, "_write_learning_mode_shadow_report", lambda *_args, **_kwargs: calls.append("_write_learning_mode_shadow_report") or "shadow.json")
    # Shadow no-ops (overridden by P-L59C-R1 parity/fail-open tests)
    monkeypatch.setattr(runner, "_persist_selection_ledger_shadow",
                        lambda **kw: (calls.append("P-L53:selection_ledger_final"),
                                      {"status": "verified", "persist_status": "inserted"})[-1])
    monkeypatch.setattr(runner, "_persist_capital_deployment_funnel_shadow",
                        lambda **kw: (calls.append("P-L54B:capital_funnel_final"),
                                      {"status": "verified", "persist_status": "inserted"})[-1])
    return calls


def _run(monkeypatch, tmp_path, *, timing, shadow: bool = False, fail_backtest: bool = False,
         llm_selected: bool | None = None):
    calls = _patch_trading_flow(monkeypatch, shadow=shadow, fail_backtest=fail_backtest,
                                llm_selected=llm_selected)
    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)
    result = _auto_paper_trade(settings, store, _Reporter(), "cycle", {"run_id": "source"}, {}, {}, timing=timing)
    return result, calls, store


def _segments(report):
    return {stage: {segment["name"] for segment in item.get("segments", [])} for stage, item in report["stages"].items()}


def test_auto_paper_trade_assigns_real_calls_to_the_required_segments(monkeypatch, tmp_path):
    timing = MarketCycleTiming(tmp_path, "integration")
    _result, calls, store = _run(monkeypatch, tmp_path, timing=timing)
    report = timing.finalize("completed")
    segments = _segments(report)

    assert "request_trade_recommendations" in calls
    assert {"structured_recommendations"} <= segments["llm_decision"]
    assert "structured_recommendations" not in segments["deterministic_gates"]
    assert {"deterministic_review", "adversarial_review", "entry_quality_gate", "backtest_gate", "order_plan_build"} <= segments["deterministic_gates"]
    assert {"recommendation_records", "signal_decision_updates", "order_plan_records", "execution_status_updates"} <= segments["persistence"]
    assert {"save_trade_recommendation", "save_order_plan", "save_broker_order"} <= set(store.calls)
    assert "submit_paper_order_plan" in calls
    assert all("submit_paper_order_plan" not in names for names in segments.values())
    assert report["segment_overlap_count"] == 0


def test_shadow_report_and_failed_segment_keep_prior_timing(monkeypatch, tmp_path):
    timing = MarketCycleTiming(tmp_path, "failed")
    try:
        _run(monkeypatch, tmp_path, timing=timing, fail_backtest=True)
    except RuntimeError as exc:
        assert str(exc) == "backtest failed"
    report = timing.finalize("failed")
    assert report["stages"]["llm_decision"]["status"] == "completed"
    assert report["stages"]["deterministic_gates"]["status"] == "failed"
    assert next(item for item in report["stages"]["deterministic_gates"]["segments"] if item["name"] == "backtest_gate")["status"] == "failed"

    shadow_timing = MarketCycleTiming(tmp_path, "shadow")
    _run(monkeypatch, tmp_path, timing=shadow_timing, shadow=True)
    shadow_segments = _segments(shadow_timing.finalize("completed"))
    assert "learning_shadow_report" in shadow_segments["report_generation"]
    assert "execution_status_updates" in shadow_segments["persistence"]


def test_timing_none_preserves_the_observable_flow(monkeypatch, tmp_path):
    without_timing = _run(monkeypatch, tmp_path / "without", timing=None)
    with_timing = _run(monkeypatch, tmp_path / "with", timing=MarketCycleTiming(tmp_path / "with", "with"))

    assert without_timing[0] == with_timing[0]
    assert without_timing[1] == with_timing[1]
    assert without_timing[2].calls == with_timing[2].calls


def test_comparable_capture_uses_final_plans_after_real_filters(monkeypatch, tmp_path):
    import agente_bolsa.cycle_runner as runner

    calls = _patch_trading_flow(monkeypatch)
    captured: dict[str, object] = {}

    def capture(**kwargs):
        calls.append("comparable_control_capture")
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(runner, "build_comparable_control_sets", capture)
    def shadow_final(**kwargs):
        calls.append("shadow_final")
        captured["shadow_final"] = kwargs
        return {"status": "available"}

    monkeypatch.setattr(runner, "_persist_learning_penalty_cycle_shadow_final", shadow_final)
    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)
    runner._auto_paper_trade(
        settings,
        store,
        _Reporter(),
        "cycle",
        {"run_id": "source"},
        {},
        {},
        learning_penalty_shadow={"phase": "pre_decision"},
    )
    assert calls.index("build_order_plans") < calls.index("_apply_daily_buy_limit")
    assert calls.index("_apply_low_sample_daily_quota") < calls.index("_separate_strategy_paused_plans")
    assert calls.index("_separate_strategy_paused_plans") < calls.index("comparable_control_capture")
    assert calls.index("comparable_control_capture") < calls.index("shadow_final")
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]
    assert len(captured["plans"]) == 1
    assert captured["rejected_order_plans"] == []


def test_stage_order_full_flow_with_pl53_pl54_spies(monkeypatch, tmp_path):
    """P-L59B-T-R5: stage order con identidades reales del modelo.

    OrderPlan NO define plan_id (models.py:117-134). plan_id nace al
    construir plan_records (save_order_plan). Las identidades se
    contrastan por campos reales: symbol, side, decision_lineage,
    recommendation identity.

    Rama ejecutada: exitosa con plan y submit (2399/2412).
    Rama sin submit (2255/2266) en rama sin planes.
    """
    import agente_bolsa.cycle_runner as runner

    def _plan_identity(p):
        """Identidad estructurada de plan: symbol + side + signal_id."""
        if hasattr(p, "symbol"):
            sym = str(getattr(p, "symbol", "") or "")
            side = str(getattr(p, "side", "") or "")
            dl = getattr(p, "decision_lineage", {}) or {}
            sid = str(dl.get("signal_id", ""))
        elif isinstance(p, dict):
            sym = str(p.get("symbol", ""))
            side = str(p.get("side", ""))
            dl = p.get("decision_lineage") or {}
            sid = str(dl.get("signal_id", p.get("signal_id", "")))
        else:
            return "unknown"
        return f"{sym}|{side}|{sid}"

    def _rec_identity(r):
        """Identidad de recomendacion: symbol + action + signal_id."""
        sym = getattr(r, "symbol", "")
        act = getattr(r, "action", "")
        dl = getattr(r, "decision_lineage", {}) or {}
        sid = str(dl.get("signal_id", ""))
        return f"{sym}|{act}|{sid}"

    calls = _patch_trading_flow(monkeypatch)
    captured: dict[str, object] = {}

    def spy_comparable(**kwargs):
        calls.append("P-L31B:comparable_control_capture")
        pw = list(kwargs.get("plans", []))
        captured["P-L31B"] = {
            "plans_count": len(pw),
            "plan_identities": sorted(_plan_identity(p) for p in pw),
        }
        return {}

    monkeypatch.setattr(runner, "build_comparable_control_sets", spy_comparable)

    def spy_selection_ledger(**kwargs):
        calls.append("P-L53:selection_ledger_final")
        pl = list(kwargs.get("plans", []))
        prl = list(kwargs.get("plan_records", []))
        rl = list(kwargs.get("recommendations", []))
        captured["P-L53"] = {
            "plan_identities": sorted(_plan_identity(p) for p in pl),
            "plan_record_ids": sorted(str(pr.get("plan_id", "")) for pr in prl if isinstance(pr, dict)),
            "plan_record_lineages": sorted(
                str((pr.get("decision_lineage", {}) or {}).get("signal_id", ""))
                for pr in prl if isinstance(pr, dict)
            ),
            "rec_identities": sorted(_rec_identity(r) for r in rl),
            "has_plan_records": bool(prl),
            "has_ordered": bool(kwargs.get("ordered_records")),
        }
        return {"status": "verified", "persist_status": "inserted"}

    monkeypatch.setattr(runner, "_persist_selection_ledger_shadow", spy_selection_ledger)

    def spy_capital_funnel(**kwargs):
        calls.append("P-L54B:capital_funnel_final")
        pl = list(kwargs.get("plans", []))
        rl = list(kwargs.get("recommendations", []))
        gl = list(kwargs.get("gated_recommendations", []))
        captured["P-L54B"] = {
            "plan_ids": sorted(
                str(getattr(p, "plan_id", p.get("plan_id", "") if isinstance(p, dict) else ""))
                for p in pl
            ),
            "rec_identities": sorted(_rec_identity(r) for r in rl),
            "has_gated": bool(gl),
            "has_submitted": bool(kwargs.get("submitted")),
        }
        return {"status": "verified", "persist_status": "inserted"}

    monkeypatch.setattr(runner, "_persist_capital_deployment_funnel_shadow", spy_capital_funnel)

    monkeypatch.setattr(
        runner, "_persist_learning_penalty_cycle_shadow_final",
        lambda **kw: (calls.append("P-L50:learning_penalty_shadow_final"), {"status": "available"})[-1],
    )

    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)
    runner._auto_paper_trade(
        settings, store, _Reporter(), "cycle",
        {"run_id": "source"}, {}, {},
        learning_penalty_shadow={"phase": "pre_decision"},
        selection_ledger_phase_a={"all_candidates": [], "selected_candidates": []},
    )

    # ---- Orden exacto ----
    assert calls.index("build_order_plans") < calls.index("P-L31B:comparable_control_capture")
    assert calls.index("P-L31B:comparable_control_capture") < calls.index("P-L50:learning_penalty_shadow_final")
    assert calls.index("P-L50:learning_penalty_shadow_final") < calls.index("P-L53:selection_ledger_final")
    assert calls.index("P-L53:selection_ledger_final") < calls.index("P-L54B:capital_funnel_final")

    # ---- P-L31B recibe 1 plan ----
    assert captured["P-L31B"]["plans_count"] == 1

    # ---- Contrato: plans por identidad real ----
    # P-L31B y P-L53 comparten los mismos planes por identidad semantica
    # (symbol+side+signal_id), aunque P-L53 los recibe tras replace()
    # que sustituye recommendation (cycle_runner:~2004). La decision_lineage
    # y symbol/side se preservan.
    assert captured["P-L31B"]["plan_identities"] == captured["P-L53"]["plan_identities"]

    # ---- plan_id nace en plan_records (save_order_plan) ----
    # OrderPlan no tiene plan_id. plan_records lo adquiere al persistir.
    assert captured["P-L53"]["has_plan_records"] is True
    assert len(captured["P-L53"]["plan_record_ids"]) == 1
    # plan_records preservan la identidad de lineage
    assert len(captured["P-L53"]["plan_record_lineages"]) == 1

    # P-L54B recibe plans=plan_records or plans (plan_records en rama exitosa).
    # plan_records tienen plan_id real; se contrasta contra P-L53.
    assert captured["P-L54B"]["plan_ids"] == captured["P-L53"]["plan_record_ids"]

    # ---- Recommendations compartidas P-L53/P-L54B ----
    assert captured["P-L53"]["rec_identities"] == captured["P-L54B"]["rec_identities"]
    assert captured["P-L54B"]["has_gated"] is True

    # ---- Submit en rama exitosa ----
    assert captured["P-L53"]["has_ordered"] is True
    assert captured["P-L54B"]["has_submitted"] is True

    # ---- Trading activo intacto ----
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]


# ===================================================================
# P-L59C-R1 Breach 2: paridad real _auto_paper_trade
# ===================================================================

def test_parity_auto_paper_trade_llm_selected_true(monkeypatch, tmp_path):
    """Con llm_selected=True la ruta activa es identica; no hay llamadas extra."""
    timing = MarketCycleTiming(tmp_path, "parity-true")
    result, calls, store = _run(monkeypatch, tmp_path, timing=timing, llm_selected=True)

    # Llamadas activas fijas
    assert calls.count("request_trade_recommendations") == 1
    assert calls.count("submit_paper_order_plan") == 1
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]

    # P-L53 shadow esta presente (no-op mock)
    assert "P-L53:selection_ledger_final" in calls

    # Llamadas base de _patch_trading_flow
    baseline_calls = [
        "request_trade_recommendations", "review_recommendations",
        "review_recommendations_adversarial", "_apply_entry_quality_gate",
        "_apply_backtest_gate", "update_signal_decisions",
        "build_order_plans", "_apply_daily_buy_limit",
        "_apply_low_sample_daily_quota", "_separate_strategy_paused_plans",
        "P-L53:selection_ledger_final", "P-L54B:capital_funnel_final",
        "submit_paper_order_plan", "update_signal_execution_status",
    ]
    for baseline in baseline_calls:
        assert baseline in calls, f"Llamada esperada {baseline} ausente"


def test_parity_auto_paper_trade_llm_selected_false(monkeypatch, tmp_path):
    """Con llm_selected=False la ruta activa es identica."""
    timing = MarketCycleTiming(tmp_path, "parity-false")
    result, calls, store = _run(monkeypatch, tmp_path, timing=timing, llm_selected=False)

    assert calls.count("request_trade_recommendations") == 1
    assert calls.count("submit_paper_order_plan") == 1
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]
    assert "P-L53:selection_ledger_final" in calls


def test_parity_auto_paper_trade_llm_selected_none(monkeypatch, tmp_path):
    """Con llm_selected=None (legacy) la ruta activa es identica."""
    timing = MarketCycleTiming(tmp_path, "parity-none")
    result, calls, store = _run(monkeypatch, tmp_path, timing=timing, llm_selected=None)

    assert calls.count("request_trade_recommendations") == 1
    assert calls.count("submit_paper_order_plan") == 1
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]
    assert "P-L53:selection_ledger_final" in calls


def test_parity_p53_receives_llm_selected_true_from_real_route(monkeypatch, tmp_path):
    """P-L53 recibe llm_selected=True por la ruta real de _auto_paper_trade."""
    import agente_bolsa.cycle_runner as runner
    captured_llm_sel: list = []

    _patch_trading_flow(monkeypatch, llm_selected=True)
    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)

    def spy_ledger(**kwargs):
        recs = list(kwargs.get("recommendations", []))
        for r in recs:
            val = getattr(r, "llm_selected", None)
            captured_llm_sel.append(val)
        return {"status": "verified", "persist_status": "inserted"}

    monkeypatch.setattr(runner, "_persist_selection_ledger_shadow", spy_ledger)
    monkeypatch.setattr(runner, "_persist_capital_deployment_funnel_shadow",
                        lambda **kw: {"status": "verified", "persist_status": "inserted"})

    runner._auto_paper_trade(
        settings, store, _Reporter(), "cycle", {"run_id": "source"}, {}, {},
        selection_ledger_phase_a={"all_candidates": [], "selected_candidates": []},
    )

    assert len(captured_llm_sel) >= 1
    assert captured_llm_sel[0] is True
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]


def test_parity_p53_receives_llm_selected_false_from_real_route(monkeypatch, tmp_path):
    """P-L53 recibe llm_selected=False por la ruta real."""
    import agente_bolsa.cycle_runner as runner
    captured_llm_sel: list = []

    _patch_trading_flow(monkeypatch, llm_selected=False)
    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)

    def spy_ledger(**kwargs):
        recs = list(kwargs.get("recommendations", []))
        for r in recs:
            val = getattr(r, "llm_selected", None)
            captured_llm_sel.append(val)
        return {"status": "verified", "persist_status": "inserted"}

    monkeypatch.setattr(runner, "_persist_selection_ledger_shadow", spy_ledger)
    monkeypatch.setattr(runner, "_persist_capital_deployment_funnel_shadow",
                        lambda **kw: {"status": "verified", "persist_status": "inserted"})

    runner._auto_paper_trade(
        settings, store, _Reporter(), "cycle", {"run_id": "source"}, {}, {},
        selection_ledger_phase_a={"all_candidates": [], "selected_candidates": []},
    )

    assert len(captured_llm_sel) >= 1
    assert captured_llm_sel[0] is False
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]


def test_parity_all_three_yield_identical_calls_and_store(monkeypatch, tmp_path):
    """True/False/None producen identicas llamadas activas y store."""
    results: list[tuple] = []
    labels = {True: "comp-true", False: "comp-false", None: "comp-none"}
    for val in (True, False, None):
        label = labels[val]
        t = MarketCycleTiming(tmp_path, label)
        result, calls, store = _run(monkeypatch, tmp_path,
                                     timing=t, llm_selected=val)
        results.append((calls, store.calls))

    baseline = results[0]
    for other in results[1:]:
        assert other[0] == baseline[0], "calls difieren entre True/False/None"
        assert other[1] == baseline[1], "store.calls difieren entre True/False/None"


# ===================================================================
# P-L59C-R1 Breach 3: fail-open en ruta real
# ===================================================================

def test_fail_open_selection_ledger_does_not_block_route(monkeypatch, tmp_path):
    """Si build_canonical_selection_ledger lanza, la ruta activa completa sin cambios."""
    import agente_bolsa.cycle_runner as runner

    # Capture the real function before _patch_trading_flow replaces it
    from agente_bolsa.cycle_runner import _persist_selection_ledger_shadow as real_persist_shadow

    spy_calls: list[str] = []

    def failing_build(*_args, **_kwargs):
        spy_calls.append("build_attempted")
        raise RuntimeError("forced_shadow_failure")

    # Replace build_canonical_selection_ledger BEFORE _patch_trading_flow
    # (it's NOT patched by _patch_trading_flow, so no conflict)
    monkeypatch.setattr(runner, "build_canonical_selection_ledger", failing_build)

    calls = _patch_trading_flow(monkeypatch)

    # Restore the real _persist_selection_ledger_shadow so it actually
    # calls build_canonical_selection_ledger (which now raises)
    monkeypatch.setattr(runner, "_persist_selection_ledger_shadow", real_persist_shadow)

    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)

    result = runner._auto_paper_trade(
        settings, store, _Reporter(), "cycle",
        {"run_id": "source"}, {}, {},
        learning_penalty_shadow={"phase": "pre_decision"},
        selection_ledger_phase_a={"all_candidates": [], "selected_candidates": []},
    )

    # El shadow intento construir (y fallo)
    assert "build_attempted" in spy_calls

    # La ruta activa se completo
    assert "request_trade_recommendations" in calls
    assert "submit_paper_order_plan" in calls
    assert store.calls == ["save_trade_recommendation", "save_order_plan", "save_broker_order"]

    # El resultado del ledger es unavailable
    assert result["selection_ledger"]["status"] == "unavailable"
    assert result["selection_ledger"]["persist_status"] == "failed"


# ===================================================================
# P-L59C-R2: paridad economica real (payloads, no solo nombres)
# ===================================================================

# ===================================================================
# P-L59C-R4: paridad con normalizacion context-aware
# ===================================================================


def _strip_observational_minimal(obj: dict, *, inside_dcs: bool = False) -> dict:
    """Context-aware: solo llm_selected global; content_hash+captured_at solo en raiz DCS/CCS.

    - Globalmente (todos los niveles): retira llm_selected.
    - Solo en el NIVEL RAIZ exacto de decision_context_snapshot o
      comparable_control_set: retira content_hash y captured_at.
    - Dentro de DCS/CCS, los subbloques anidados (market_state_ref, gates, etc.)
      conservan sus propios content_hash/captured_at intactos.
    - snapshot_id, IDs canonicos y campos economicos siempre conservados.
    """
    OBS_BLOCKS = {"decision_context_snapshot", "comparable_control_set"}
    out = {}
    for k, v in obj.items():
        if k == "llm_selected":
            continue
        if inside_dcs and k in ("content_hash", "captured_at"):
            continue
        if isinstance(v, dict):
            # Only descend into OBS_BLOCKS with strip flag; children inherit False
            next_dcs = (k in OBS_BLOCKS)
            out[k] = _strip_observational_minimal(v, inside_dcs=next_dcs)
        elif isinstance(v, list):
            # List items are not direct children of DCS/CCS root;
            # pass inside_dcs=False.  If an item dict happens to contain
            # an OBS_BLOCK key, the normal recursion will detect it.
            out[k] = [
                _strip_observational_minimal(i, inside_dcs=False)
                if isinstance(i, dict) else i
                for i in v
            ]
        else:
            out[k] = v
    return out


def _capture_parity_run(monkeypatch, tmp_path, llm_selected):
    """Run _auto_paper_trade with frozen IDs and return minimal-stripped payloads."""
    from dataclasses import asdict, is_dataclass

    import agente_bolsa.cycle_runner as runner

    # Freeze new_id so all three runs produce identical deterministic IDs
    _id_seq = iter(f"ID-{i:04d}" for i in range(100))
    monkeypatch.setattr(runner, "new_id", lambda prefix: next(_id_seq))

    _patch_trading_flow(monkeypatch, llm_selected=llm_selected)
    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)

    result = runner._auto_paper_trade(
        settings, store, _Reporter(), "cycle",
        {"run_id": "source"}, {}, {},
        learning_penalty_shadow={"phase": "pre_decision"},
        selection_ledger_phase_a={"all_candidates": [], "selected_candidates": []},
    )

    def _as_dict_recursive(obj):
        if is_dataclass(obj):
            return {k: _as_dict_recursive(v) for k, v in asdict(obj).items()}
        if isinstance(obj, dict):
            return {k: _as_dict_recursive(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_as_dict_recursive(i) for i in obj]
        return obj

    return {
        "calls": list(store.calls),
        "rec_payloads": [_strip_observational_minimal(_as_dict_recursive(p)) for p in store.rec_payloads],
        "plan_payloads": [_strip_observational_minimal(_as_dict_recursive(p)) for p in store.plan_payloads],
        "broker_payloads": [_strip_observational_minimal(_as_dict_recursive(p)) for p in store.broker_payloads],
        "submitted": result.get("submitted"),
        "failed": result.get("failed"),
    }


def test_economic_parity_true_false_none_identical_payloads(monkeypatch, tmp_path):
    """Tras retirar solo llm_selected/hashes/captured_at, los payloads son identicos.

    Conserva recommendation_id, plan_id, broker_order_id, signal_id,
    decision_context_snapshot (salvo llm_selected y hashes), submitted/failed completos.
    """
    true_run = _capture_parity_run(monkeypatch, tmp_path / "true", True)
    false_run = _capture_parity_run(monkeypatch, tmp_path / "false", False)
    none_run = _capture_parity_run(monkeypatch, tmp_path / "none", None)

    # Submitted/failed identicos (full values, not booleans)
    assert true_run["submitted"] == false_run["submitted"] == none_run["submitted"]
    assert true_run["failed"] == false_run["failed"] == none_run["failed"]

    # Store call sequence identica
    assert true_run["calls"] == false_run["calls"] == none_run["calls"]

    # Rec payloads contienen IDs canonicos y decision_context_snapshot
    for key in ("rec_payloads", "plan_payloads", "broker_payloads"):
        assert true_run[key] == false_run[key], f"{key} difiere True vs False"
        assert true_run[key] == none_run[key], f"{key} difiere True vs None"

    # Negative assertions: IDs canonicos y campos economicos preservados
    for run in (true_run, false_run, none_run):
        rp = run["rec_payloads"]
        assert len(rp) >= 1, "Debe haber al menos un rec payload"
        assert "recommendation_id" in rp[0], "recommendation_id debe conservarse"
        assert isinstance(rp[0]["recommendation_id"], str), "recommendation_id str"
        assert rp[0]["symbol"] == "AAPL", "symbol debe conservarse"
        assert rp[0]["action"] == "buy", "action debe conservarse"
        assert rp[0]["confidence"] == 0.9, "confidence debe conservarse"
        # decision_context_snapshot conservado (salvo llm_selected, content_hash, captured_at)
        if "decision_context_snapshot" in rp[0]:
            dcs = rp[0]["decision_context_snapshot"]
            assert "cycle_id" in dcs, "cycle_id en snapshot"
            assert "decision_source" in dcs, "decision_source en snapshot"
            assert "llm_selected" not in dcs, "llm_selected retirado"
            assert "content_hash" not in dcs, "content_hash retirado (deriva del snapshot)"
            assert "captured_at" not in dcs, "captured_at retirado (deriva del snapshot)"
            # snapshot_id NO depende de llm_selected: se conserva
            assert "snapshot_id" in dcs, "snapshot_id conservado en DCS"
            assert isinstance(dcs["snapshot_id"], str), "snapshot_id str"

        pp = run["plan_payloads"]
        assert len(pp) >= 1, "Debe haber al menos un plan payload"
        assert "plan_id" in pp[0], "plan_id debe conservarse"
        assert isinstance(pp[0]["plan_id"], str), "plan_id str"
        assert "symbol" in pp[0], "symbol en plan"
        assert "side" in pp[0], "side en plan"

        bp = run["broker_payloads"]
        assert len(bp) >= 1, "Debe haber al menos un broker payload"
        assert "broker_order_id" in bp[0], "broker_order_id debe conservarse"
        assert isinstance(bp[0]["broker_order_id"], str), "broker_order_id str"
        assert "symbol" in bp[0] or "order" in bp[0], "identidad en broker payload"

    # snapshot_id identico en las tres ejecuciones (no depende de llm_selected)
    # Solo si decision_context_snapshot esta presente (mock puede no producirlo).
    def _dcs_snapshot_id(run):
        for rp in run["rec_payloads"]:
            dcs = rp.get("decision_context_snapshot", {})
            if dcs and "snapshot_id" in dcs:
                return dcs["snapshot_id"]
        return None

    sid_true = _dcs_snapshot_id(true_run)
    sid_false = _dcs_snapshot_id(false_run)
    sid_none = _dcs_snapshot_id(none_run)
    if sid_true is not None:
        assert sid_true == sid_false == sid_none, (
            f"snapshot_id identico en True/False/None: {sid_true} vs {sid_false} vs {sid_none}"
        )


def test_strip_context_aware_preserves_external_hashes():
    """content_hash fuera de DCS/CCS y en subbloques anidados sobrevive."""
    payload = {
        "llm_selected": True,                     # debe retirarse globalmente
        "recommendation_id": "rec-123",
        "content_hash": "abc123",                  # externo: se conserva
        "captured_at": "2026-07-27T20:00:00Z",    # externo: se conserva
        "snapshot_id": "snap-999",                 # externo: se conserva
        "decision_context_snapshot": {
            "llm_selected": True,                  # DCS root: debe retirarse
            "content_hash": "dcs-hash",            # DCS root: debe retirarse
            "captured_at": "2026-07-27T19:00:00Z", # DCS root: debe retirarse
            "snapshot_id": "snap-001",             # DCS root: se conserva
            "cycle_id": "c1",
            "decision_source": "llm",
            "market_state_ref": {                  # nested: se conserva integro (salvo llm_selected)
                "content_hash": "msr-hash",         # nested: se conserva
                "captured_at": "2026-07-27T18:00:00Z", # nested: se conserva
                "status": "available",
            },
            "gate_evaluation": {                   # nested: se conserva integro
                "content_hash": "gate-hash",
                "captured_at": "2026-07-27T17:00:00Z",
            },
        },
        "comparable_control_set": {
            "content_hash": "ccs-hash",            # CCS root: debe retirarse
            "captured_at": "2026-07-27T18:00:00Z", # CCS root: debe retirarse
            "snapshot_id": "snap-002",             # CCS root: se conserva
            "status": "verified",
        },
    }
    result = _strip_observational_minimal(payload)

    # Global: llm_selected removed
    assert "llm_selected" not in result

    # External fields preserved
    assert result["content_hash"] == "abc123"
    assert result["captured_at"] == "2026-07-27T20:00:00Z"
    assert result["snapshot_id"] == "snap-999"
    assert result["recommendation_id"] == "rec-123"

    # DCS root: llm_selected, content_hash, captured_at removed
    dcs = result["decision_context_snapshot"]
    assert "llm_selected" not in dcs
    assert "content_hash" not in dcs
    assert "captured_at" not in dcs
    assert dcs["snapshot_id"] == "snap-001"
    assert dcs["cycle_id"] == "c1"
    assert dcs["decision_source"] == "llm"

    # DCS nested market_state_ref: content_hash/captured_at SURVIVEN
    msr = dcs["market_state_ref"]
    assert msr["content_hash"] == "msr-hash"
    assert msr["captured_at"] == "2026-07-27T18:00:00Z"
    assert msr["status"] == "available"

    # DCS nested gate_evaluation: content_hash/captured_at SURVIVEN
    gate = dcs["gate_evaluation"]
    assert gate["content_hash"] == "gate-hash"
    assert gate["captured_at"] == "2026-07-27T17:00:00Z"

    # CCS root: content_hash, captured_at removed; snapshot_id preserved
    ccs = result["comparable_control_set"]
    assert "content_hash" not in ccs
    assert "captured_at" not in ccs
    assert ccs["snapshot_id"] == "snap-002"
    assert ccs["status"] == "verified"


def test_strip_preserves_list_item_hashes_inside_dcs():
    """Lista dentro de DCS: items conservan content_hash/captured_at; llm_selected global retirado."""
    payload = {
        "decision_context_snapshot": {
            "content_hash": "dcs-root-hash",       # DCS root: retirado
            "captured_at": "t-root",               # DCS root: retirado
            "snapshot_id": "s1",
            "controls": [                           # lista dentro de DCS
                {"content_hash": "ctrl-hash-1", "llm_selected": True, "symbol": "A"},
                {"content_hash": "ctrl-hash-2", "captured_at": "t-ctrl", "symbol": "B"},
            ],
        },
    }
    result = _strip_observational_minimal(payload)
    dcs = result["decision_context_snapshot"]
    assert "content_hash" not in dcs   # root stripped
    assert "captured_at" not in dcs    # root stripped
    assert dcs["snapshot_id"] == "s1"

    controls = dcs["controls"]
    # Item 0: content_hash preserved, llm_selected stripped
    assert controls[0]["content_hash"] == "ctrl-hash-1"
    assert "llm_selected" not in controls[0]
    assert controls[0]["symbol"] == "A"
    # Item 1: captured_at preserved (not root), content_hash preserved
    assert controls[1]["content_hash"] == "ctrl-hash-2"
    assert controls[1]["captured_at"] == "t-ctrl"
    assert controls[1]["symbol"] == "B"
