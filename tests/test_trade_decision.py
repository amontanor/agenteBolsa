import json
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot, TradeRecommendation
from agente_bolsa.tools.trade_decision import (
    _compact_sentiment_for_prompt,
    _compact_technical_context_for_prompt,
    _candidate_learning_features,
    _candidate_learning_prior,
    _annotate_technical_context_with_learning,
    _build_decision_learning_context,
    augment_recommendations_with_deterministic_fallback,
    deterministic_trade_fallback_recommendations,
    _llm_prompt_payload,
    _select_deterministic_candidates,
    _sizing_adjustment_for_recommendation,
    _floor_qty,
    _latest_report,
    load_latest_technical_candidates,
    _prior_profile_key,
    _recommendation_from_dict,
    _selection_score_for_candidate,
    build_order_plans,
    filter_entry_quality,
    validate_entry_quality,
)
from agente_bolsa.tools.deterministic_reviewer import review_recommendations
from agente_bolsa.tools.adversarial_reviewer import review_recommendations_adversarial


def test_recommendation_normalizes_percent_exposure_to_fraction():
    recommendation = _recommendation_from_dict(
        {
            "symbol": "AAPL",
            "action": "buy",
            "confidence": 0.8,
            "reason": "test",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "target_exposure_pct": 5.0,
        }
    )

    assert recommendation is not None
    assert recommendation.target_exposure_pct == 0.05


def test_latest_report_ignores_manifest_files(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report = reports_dir / "closed_market_technical_study_real.json"
    manifest = reports_dir / "closed_market_technical_study_real.manifest.json"
    report.write_text("{}", encoding="utf-8")
    manifest.write_text("{}", encoding="utf-8")
    manifest.touch()

    selected = _latest_report(tmp_path, "closed_market_technical_study")

    assert selected == report


def test_compact_technical_context_for_prompt_drops_large_all_candidates_payload():
    technical_context = {
        "source": "intraday",
        "selected_candidates": [
            {
                "symbol": "AAPL",
                "direction": "long",
                "score": 16,
                "setup_name": "orderly_breakout",
                "rank_priority_score": 0.08,
                "rank_priority_reason": "recent_edge,volume_confirmation",
                "setup_edge_3d": 0.03,
                "effective_setup_edge_3d": 0.03,
                "setup_win_rate_3d": 0.62,
                "setup_matured_3d": 18,
                "operational_penalty": 0.0,
                "reasons": ["breakout", "volume"],
                "technical_state": {
                    "close": 100.0,
                    "rsi_14": 64.0,
                    "sma_20": 94.0,
                    "sma_50": 90.0,
                    "sma_200": 80.0,
                    "volume_zscore_20": 1.4,
                    "candlestick_patterns": ["strong_close"] * 10,
                    "chart_patterns": [{"pattern": "flag"}] * 10,
                },
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 112.0},
            }
        ],
        "all_candidates": [{"symbol": f"SYM{i}", "score": i} for i in range(200)],
    }

    compact = _compact_technical_context_for_prompt(technical_context)

    assert "all_candidates" not in compact
    assert len(compact["selected_candidates"]) == 1
    assert len(compact["selected_candidates"][0]["technical_state"]["candlestick_patterns"]) == 3
    assert len(compact["selected_candidates"][0]["technical_state"]["chart_patterns"]) == 3
    assert "selection_metadata" in compact


def test_compact_technical_context_for_prompt_uses_configurable_selected_limit():
    selected = [
        {
            "symbol": f"LONG{i}",
            "direction": "long",
            "score": 16,
            "technical_state": {},
            "risk_plan": {},
        }
        for i in range(16)
    ]

    compact = _compact_technical_context_for_prompt({"selected_candidates": selected}, selected_limit=16)

    assert len(compact["selected_candidates"]) == 16
    assert compact["selected_candidates"][-1]["symbol"] == "LONG15"


def test_llm_prompt_payload_hides_top_shorts_when_short_selling_disabled():
    settings = Settings()
    portfolio = PortfolioSnapshot(
        account_id="acct",
        status="ACTIVE",
        currency="USD",
        cash=10000,
        portfolio_value=10000,
        buying_power=10000,
        positions=[],
        open_orders=[],
    )
    selected = [{"symbol": f"LONG{i}", "direction": "long", "score": 16, "technical_state": {}, "risk_plan": {}} for i in range(12)]
    technical_context = {
        "selected_candidates": selected,
        "top_longs": selected,
        "top_shorts": [{"symbol": "TSLA", "direction": "short", "score": 14, "technical_state": {}, "risk_plan": {}}],
    }

    payload = _llm_prompt_payload(
        settings,
        portfolio,
        technical_context,
        {"results": []},
        {},
        {},
        {},
        {},
        compact=True,
    )

    assert payload["risk_limits"]["allow_short_selling"] is False
    assert payload["technical_candidates"]["top_shorts"] == []
    assert payload["risk_limits"]["effective_max_orders_per_cycle"] == 5
    assert payload["risk_limits"]["effective_max_daily_buy_orders"] == 5
    assert payload["risk_limits"]["prefer_full_long_only_capacity"] is True


def _selection_candidate(symbol: str, *, score: int, return_20d: float = 0.08, **technical_state):
    state = {
        "close": 100.0,
        "return_20d": return_20d,
        "sma_20": 95.0,
        "rsi_14": 66.0,
        "macd": 2.0,
        "macd_signal": 1.0,
        "volume_zscore_20": 0.2,
        "chart_patterns": [],
    }
    state.update(technical_state)
    return {
        "symbol": symbol,
        "direction": "long",
        "score": score,
        "setup_quality": "strong",
        "relative_return_20d": 0.05,
        "technical_state": state,
        "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 115.0},
    }


def test_select_deterministic_candidates_ranks_lower_score_with_better_edge_first():
    strong = _selection_candidate(
        "STRONG",
        score=14,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    weak = _selection_candidate("WEAK", score=19)
    strong_key = _prior_profile_key(_candidate_learning_features(strong))
    weak_key = _prior_profile_key(_candidate_learning_features(weak))
    digest = {
        "setup_stats_3d": [
            {"setup": "confirmed_pattern", "avg_return": 0.02, "win_rate": 0.6, "matured": 40},
            {"setup": "baseline_trend", "avg_return": -0.01, "win_rate": 0.35, "matured": 40},
        ],
        "setup_priors_3d": [
            {"profile_key": strong_key, "setup": "confirmed_pattern", "expected_edge": 0.04, "matured": 35, "win_rate": 0.7},
            {"profile_key": weak_key, "setup": "baseline_trend", "expected_edge": -0.01, "matured": 35, "win_rate": 0.35},
        ],
    }

    selected, metadata = _select_deterministic_candidates(
        [weak, strong],
        digest,
        {},
        limit=2,
        settings=Settings(SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=False),
    )

    assert selected[0]["symbol"] == "STRONG"
    assert selected[0]["selection_score"] > selected[1]["selection_score"]
    assert metadata["promoted_over_score_rank"][0]["symbol"] == "STRONG"


def test_select_deterministic_candidates_shrinks_small_sample_extreme_edge():
    tiny = _selection_candidate("TINY", score=13)
    stable = _selection_candidate(
        "STABLE",
        score=14,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    tiny_key = _prior_profile_key(_candidate_learning_features(tiny))
    stable_key = _prior_profile_key(_candidate_learning_features(stable))
    digest = {
        "setup_stats_3d": [
            {"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.45, "matured": 40},
            {"setup": "confirmed_pattern", "avg_return": 0.02, "win_rate": 0.6, "matured": 40},
        ],
        "setup_priors_3d": [
            {"profile_key": tiny_key, "setup": "baseline_trend", "expected_edge": 0.25, "matured": 3, "win_rate": 1.0},
            {"profile_key": stable_key, "setup": "confirmed_pattern", "expected_edge": 0.03, "matured": 35, "win_rate": 0.65},
        ],
    }

    selected, _metadata = _select_deterministic_candidates(
        [tiny, stable],
        digest,
        {},
        limit=2,
        settings=Settings(SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=False),
    )

    assert selected[0]["symbol"] == "STABLE"
    assert selected[1]["symbol"] == "TINY"


def test_select_deterministic_candidates_promotes_high_conviction_confirmed_momentum():
    high_conviction = _selection_candidate(
        "CSCO",
        score=16,
        rsi_14=71.4,
        volume_zscore_20=2.75,
        chart_patterns=[
            {"bias": "bullish", "status": "confirmed"},
            {"bias": "bullish", "status": "confirmed"},
        ],
    )
    high_conviction["technical_state"]["close"] = 110.0
    high_conviction["technical_state"]["sma_20"] = 100.0

    weaker = _selection_candidate(
        "WEAKER",
        score=18,
        rsi_14=68.0,
        volume_zscore_20=-1.4,
        chart_patterns=[],
    )

    digest = {
        "setup_stats_3d": [
            {"setup": "confirmed_pattern", "avg_return": 0.0, "win_rate": 0.5, "matured": 20},
            {"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20},
        ]
    }

    selected, _metadata = _select_deterministic_candidates([weaker, high_conviction], digest, {}, limit=2)

    assert selected[0]["symbol"] == "CSCO"
    assert "high_conviction_confirmed_momentum" in selected[0]["selection_reason"]
    assert selected[0]["selection_components"]["high_conviction_momentum_component"] > 0


def test_select_deterministic_candidates_promotes_leader_momentum_extension_despite_weak_volume():
    leader = _selection_candidate(
        "DDOG",
        score=13,
        rsi_14=83.4,
        volume_zscore_20=-2.4,
        close_position_in_range=0.91,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    leader["technical_state"]["close"] = 114.0
    leader["technical_state"]["sma_20"] = 100.0
    leader["relative_return_20d"] = 0.18

    plain = _selection_candidate(
        "PLAIN",
        score=16,
        rsi_14=67.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    digest = {
        "setup_stats_3d": [
            {"setup": "confirmed_pattern", "avg_return": 0.0, "win_rate": 0.5, "matured": 20},
            {"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20},
        ]
    }

    selected, _metadata = _select_deterministic_candidates([plain, leader], digest, {}, limit=2)

    assert selected[0]["symbol"] == "DDOG"
    assert "leader_momentum_extension" in selected[0]["selection_reason"]
    assert selected[0]["selection_components"]["leader_momentum_extension_component"] > 0
    assert selected[0]["selection_components"]["volume_component"] == 0.0


def test_load_latest_technical_candidates_builds_selected_candidates_from_all_candidates(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    weak = _selection_candidate("WEAK", score=18)
    strong = _selection_candidate("STRONG", score=14, volume_zscore_20=1.6, chart_patterns=[])
    report = {
        "run_id": "scan-test",
        "as_of": "2026-05-22T20:00:00Z",
        "top_longs": [weak, strong],
        "top_shorts": [],
        "all_candidates": [weak, strong],
    }
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [
                    {"setup": "trend_volume", "avg_return": 0.02, "win_rate": 0.6, "matured": 40},
                    {"setup": "baseline_trend", "avg_return": -0.01, "win_rate": 0.35, "matured": 40},
                ]
            }
            ),
        encoding="utf-8",
    )

    context = load_latest_technical_candidates(tmp_path, per_side=1)

    assert context["top_longs"][0]["symbol"] == "WEAK"
    assert context["selected_candidates"][0]["symbol"] == "STRONG"
    assert context["selection_metadata"]["eligible"] == 2


def test_load_latest_technical_candidates_expands_long_only_selection_budget(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        _selection_candidate(
            f"SYM{i}",
            score=20 - i,
            chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
            volume_zscore_20=1.0,
        )
        for i in range(12)
    ]
    report = {
        "run_id": "scan-test",
        "as_of": "2026-05-22T20:00:00Z",
        "top_longs": candidates,
        "top_shorts": [],
        "all_candidates": candidates,
    }
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    (reports_dir / "latest_daily_learning_digest.json").write_text(json.dumps({}), encoding="utf-8")

    context = load_latest_technical_candidates(tmp_path, per_side=1)

    assert len(context["selected_candidates"]) == 12
    assert context["selected_candidates"][0]["symbol"] == "SYM0"


def test_load_latest_technical_candidates_uses_trade_selection_top_n(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        _selection_candidate(
            f"SYM{i}",
            score=20 - i,
            chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
            volume_zscore_20=1.0,
        )
        for i in range(16)
    ]
    report = {
        "run_id": "scan-test",
        "as_of": "2026-05-22T20:00:00Z",
        "top_longs": candidates,
        "top_shorts": [],
        "all_candidates": candidates,
    }
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    (reports_dir / "latest_daily_learning_digest.json").write_text(json.dumps({}), encoding="utf-8")

    context = load_latest_technical_candidates(tmp_path, per_side=1)

    assert len(context["selected_candidates"]) == 16
    assert context["selected_candidates"][-1]["symbol"] == "SYM15"


def test_deterministic_trade_fallback_uses_selected_candidates_without_llm():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    candidate = _selection_candidate("FSLR", score=18, volume_zscore_20=1.2)
    candidate["selection_score"] = 0.04
    candidate["selection_rank"] = 1
    context = {"selected_candidates": [candidate]}

    recommendations = deterministic_trade_fallback_recommendations(Settings(), portfolio, context)

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "FSLR"
    assert recommendations[0].action == "buy"
    assert recommendations[0].source == "deterministic_fallback"
    assert recommendations[0].confidence >= 0.65


def test_deterministic_trade_fallback_blocks_partial_market_state_with_missing_macro():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    candidate = _selection_candidate("FRT", score=18, volume_zscore_20=1.2)
    candidate["selection_score"] = 0.04
    candidate["selection_rank"] = 1
    context = {"selected_candidates": [candidate]}
    market_state = {
        "data_quality": {
            "status": "PARTIAL",
            "notes": ["macro_summary_missing"],
            "data_vendor_quality": "informal",
        }
    }

    recommendations = deterministic_trade_fallback_recommendations(
        Settings(),
        portfolio,
        context,
        market_state=market_state,
    )
    merged, metadata = augment_recommendations_with_deterministic_fallback(
        Settings(),
        portfolio,
        context,
        [],
        market_state=market_state,
    )

    assert recommendations == []
    assert merged == []
    assert metadata["blocked_reason"] == "market_state_partial_missing_macro_or_news"


def test_deterministic_trade_fallback_skips_existing_positions_when_adds_disabled():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="FSLR",
                qty=1,
                market_value=100,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    candidate = _selection_candidate("FSLR", score=18, volume_zscore_20=1.2)
    candidate["selection_score"] = 0.04
    context = {"selected_candidates": [candidate]}

    recommendations = deterministic_trade_fallback_recommendations(
        Settings(ALLOW_POSITION_ADDS=False),
        portfolio,
        context,
    )

    assert recommendations == []


def test_deterministic_trade_fallback_skips_plain_overextended_candidates():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    extended = _selection_candidate("EXT", score=20, close=130.0, sma_20=100.0)
    extended["selection_score"] = 0.10
    valid = _selection_candidate("OK", score=17, close=100.0, sma_20=95.0)
    valid["selection_score"] = 0.01
    context = {"selected_candidates": [extended, valid]}

    recommendations = deterministic_trade_fallback_recommendations(Settings(), portfolio, context, limit=1)

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "OK"


def test_deterministic_trade_fallback_allows_constructive_extension_for_selected_score_thirteen(tmp_path):
    # DATA_DIR aislado: el test no debe depender de los priors del data/ vivo.
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    ddog_like = _selection_candidate(
        "DDOG",
        score=13,
        return_20d=0.2322,
        close=112.08,
        sma_20=100.0,
        rsi_14=74.12,
        volume_zscore_20=0.83,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    ddog_like["selection_rank"] = 3
    ddog_like["selection_score"] = -0.014
    context = {"selected_candidates": [ddog_like]}

    recommendations = deterministic_trade_fallback_recommendations(Settings(DATA_DIR=tmp_path), portfolio, context)

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "DDOG"
    assert recommendations[0].source == "deterministic_fallback"


def test_deterministic_trade_fallback_allows_low_score_volume_rebound():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    cohr_like = _selection_candidate(
        "COHR",
        score=8,
        return_20d=0.1177,
        rsi_14=39.22,
        macd=0.8,
        macd_signal=1.0,
        volume_zscore_20=2.9,
    )
    cohr_like["selection_rank"] = 4
    cohr_like["selection_reason"] = "profile_edge_shrunk,volume_confirmation"
    cohr_like["selection_score"] = -0.02
    context = {"selected_candidates": [cohr_like]}

    recommendations = deterministic_trade_fallback_recommendations(Settings(), portfolio, context)

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "COHR"
    assert recommendations[0].source == "deterministic_fallback"


def test_deterministic_trade_fallback_blocks_low_score_volume_rebound_outside_rsi_band():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    dis_like = _selection_candidate(
        "DIS",
        score=8,
        return_20d=0.12,
        rsi_14=56.0,
        volume_zscore_20=2.0,
    )
    dis_like["selection_rank"] = 4
    dis_like["selection_reason"] = "profile_edge_shrunk,volume_confirmation"
    dis_like["selection_score"] = -0.02
    context = {"selected_candidates": [dis_like]}

    recommendations = deterministic_trade_fallback_recommendations(Settings(), portfolio, context)

    assert recommendations == []


def test_deterministic_trade_fallback_allows_relative_strength_pullback_extension(tmp_path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    ntap_like = _selection_candidate(
        "NTAP",
        score=15,
        return_20d=0.313,
        close=118.66,
        sma_20=100.0,
        rsi_14=89.99,
        volume_zscore_20=-0.47,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    ntap_like["selection_rank"] = 9
    ntap_like["selection_reason"] = "profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,relative_strength"
    ntap_like["relative_return_20d"] = 0.2601
    ntap_like["risk_plan"] = {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 106.0}
    context = {"selected_candidates": [ntap_like]}

    recommendations = deterministic_trade_fallback_recommendations(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        portfolio,
        context,
    )

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "NTAP"
    assert recommendations[0].source == "deterministic_fallback"


def test_deterministic_trade_fallback_allows_leader_pullback_extension():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    dell_like = _selection_candidate(
        "DELL",
        score=15,
        return_20d=0.4269,
        close=127.14,
        sma_20=100.0,
        rsi_14=78.6,
        volume_zscore_20=-0.35,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    dell_like["selection_rank"] = 4
    dell_like["selection_reason"] = (
        "profile_edge_high_sample,confirmed_pattern,leader_momentum_extension,"
        "relative_strength,weak_volume_tolerated_for_leader"
    )
    dell_like["relative_return_20d"] = 0.37
    context = {"selected_candidates": [dell_like]}

    recommendations = deterministic_trade_fallback_recommendations(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        portfolio,
        context,
    )

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "DELL"
    assert recommendations[0].source == "deterministic_fallback"


def test_deterministic_trade_fallback_allows_top_long_follow_through_without_relative_strength(tmp_path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    csco_like = _selection_candidate(
        "CSCO",
        score=15,
        return_20d=0.165,
        close=116.0,
        sma_20=100.0,
        rsi_14=70.1,
        volume_zscore_20=-1.2,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    csco_like["selection_rank"] = 17
    csco_like["selection_reason"] = (
        "profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,top_long_alignment"
    )
    csco_like["relative_return_20d"] = None
    context = {"selected_candidates": [csco_like]}

    recommendations = deterministic_trade_fallback_recommendations(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        portfolio,
        context,
    )

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "CSCO"
    assert recommendations[0].source == "deterministic_fallback"


def test_augment_recommendations_replaces_hold_and_respects_buy_capacity():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    leader = _selection_candidate("SNDK", score=18, volume_zscore_20=1.4)
    leader["selection_score"] = 0.09
    leader["selection_rank"] = 1
    fill = _selection_candidate("DDOG", score=17, volume_zscore_20=1.1)
    fill["selection_score"] = 0.08
    fill["selection_rank"] = 2
    extra = _selection_candidate("MU", score=17, volume_zscore_20=1.0)
    extra["selection_score"] = 0.07
    extra["selection_rank"] = 3
    context = {"selected_candidates": [leader, fill, extra]}
    recommendations = [
        TradeRecommendation(
            symbol="SNDK",
            action="hold",
            confidence=0.82,
            reason="llm hold",
        )
    ]

    merged, metadata = augment_recommendations_with_deterministic_fallback(
        Settings(MAX_ORDERS_PER_CYCLE=2),
        portfolio,
        context,
        recommendations,
        limit=2,
    )

    buy_symbols = [item.symbol for item in merged if item.action == "buy"]
    assert buy_symbols == ["SNDK", "DDOG"]
    assert "MU" not in buy_symbols
    assert metadata["replaced_holds"] == ["SNDK"]
    assert metadata["added"] == ["SNDK", "DDOG"]
    assert next(item for item in merged if item.symbol == "SNDK").source == "deterministic_hold_override"
    assert next(item for item in merged if item.symbol == "DDOG").source == "deterministic_capacity_fill"


def test_augment_recommendations_keeps_llm_buy_and_fills_remaining_capacity():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    keep = _selection_candidate("KEEP", score=18, volume_zscore_20=1.4)
    keep["selection_score"] = 0.09
    keep["selection_rank"] = 1
    fill = _selection_candidate("FILL", score=17, volume_zscore_20=1.1)
    fill["selection_score"] = 0.08
    fill["selection_rank"] = 2
    context = {"selected_candidates": [keep, fill]}
    recommendations = [
        TradeRecommendation(
            symbol="KEEP",
            action="buy",
            confidence=0.88,
            reason="llm buy",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            target_exposure_pct=0.05,
        )
    ]

    merged, metadata = augment_recommendations_with_deterministic_fallback(
        Settings(MAX_ORDERS_PER_CYCLE=2),
        portfolio,
        context,
        recommendations,
        limit=2,
    )

    buy_symbols = [item.symbol for item in merged if item.action == "buy"]
    assert buy_symbols == ["KEEP", "FILL"]
    assert metadata["replaced_holds"] == []
    assert metadata["added"] == ["FILL"]
    assert next(item for item in merged if item.symbol == "KEEP").source == "llm"
    assert next(item for item in merged if item.symbol == "FILL").source == "deterministic_capacity_fill"


def test_compact_sentiment_for_prompt_keeps_only_candidate_symbols_and_short_news():
    technical_context = {"selected_candidates": [{"symbol": "AAPL"}]}
    sentiment_context = {
        "results": [
            {
                "symbol": "AAPL",
                "technical_direction": "long",
                "technical_score": 15,
                "news_count": 4,
                "material_risk": False,
                "sentiment": {
                    "supports_technical_setup": True,
                    "sentiment_score": 0.7,
                    "summary": "positivo",
                    "catalysts": ["earnings", "guidance", "buyback"],
                    "risks": ["valuation"],
                },
                "news": [{"title": f"headline {i}", "publisher": "pub", "published_at": "2026-05-12"} for i in range(5)],
            },
            {
                "symbol": "MSFT",
                "technical_direction": "long",
                "technical_score": 14,
                "news_count": 1,
                "material_risk": False,
                "sentiment": {"supports_technical_setup": True},
                "news": [{"title": "ignore", "publisher": "pub", "published_at": "2026-05-12"}],
            },
        ]
    }

    compact = _compact_sentiment_for_prompt(sentiment_context, technical_context)

    assert len(compact["results"]) == 1
    assert compact["results"][0]["symbol"] == "AAPL"
    assert len(compact["results"][0]["news"]) == 2


def test_floor_qty_never_rounds_fractional_position_up():
    assert _floor_qty(13.600098938) == 13.600098938
    assert _floor_qty(13.6000989389) == 13.600098938


def test_recommendation_keeps_fractional_exposure():
    recommendation = _recommendation_from_dict(
        {
            "symbol": "AAPL",
            "action": "buy",
            "confidence": 0.8,
            "reason": "test",
            "target_exposure_pct": 0.03,
        }
    )

    assert recommendation is not None
    assert recommendation.target_exposure_pct == 0.03


def test_build_order_plans_uses_whole_share_qty_for_bracket_buys(tmp_path: Path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=333.0,
        stop_loss=300.0,
        take_profit=382.5,
        target_exposure_pct=0.05,
    )

    plans = build_order_plans(Settings(DATA_DIR=tmp_path, USE_BRACKET_ORDERS=True), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].qty == 3.0
    assert plans[0].notional == 999.0
    assert plans[0].risk_decision.checks["execution_sizing"]["execution_sizing"] == "whole_share_bracket"


def test_build_order_plans_applies_micro_experiment_size_multiplier(tmp_path: Path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        target_exposure_pct=0.05,
        micro_experiment=True,
        size_multiplier=0.5,
        soft_override_reasons=["entry_score_v2_micro_experiment"],
    )

    plans = build_order_plans(Settings(DATA_DIR=tmp_path, USE_BRACKET_ORDERS=True), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].micro_experiment is True
    assert plans[0].size_multiplier == 0.5
    assert plans[0].notional == 500.0
    assert plans[0].risk_decision.checks["position_sizing"]["size_multiplier"] == 0.5


def test_build_order_plans_records_rejection_reason_when_no_plan_is_created(tmp_path: Path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )
    rejected = []

    plans = build_order_plans(
        Settings(DATA_DIR=tmp_path, USE_BRACKET_ORDERS=True, MIN_ORDER_NOTIONAL=2_000),
        portfolio,
        [recommendation],
        rejected=rejected,
    )

    assert plans == []
    assert rejected == [
        {
            "symbol": "AAPL",
            "action": "buy",
            "stage": "position_sizing",
            "reason": "below_min_order_notional",
            "checks": {
                "reason": "below_min_order_notional",
                "calculated_notional": 1000.0,
                "min_order_notional": 2000.0,
                "current_notional": 0,
                "available_position_room": 1000.0,
                "size_multiplier": 1.0,
                "target_notional": 1000.0,
                "adjusted_target_notional": 1000.0,
            },
        }
    ]


def test_build_order_plans_skips_bracket_buy_if_whole_share_too_expensive():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="EXP",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=2_000.0,
        stop_loss=1_900.0,
        take_profit=2_150.0,
        target_exposure_pct=0.05,
    )

    plans = build_order_plans(Settings(USE_BRACKET_ORDERS=True), portfolio, [recommendation])

    assert plans == []


def test_build_order_plans_blocks_duplicate_buy_symbol_within_same_cycle(tmp_path: Path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    first = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="entrada 1",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )
    second = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.92,
        reason="entrada 2",
        entry_price=101.0,
        stop_loss=96.0,
        take_profit=112.0,
        target_exposure_pct=0.05,
    )

    plans = build_order_plans(Settings(DATA_DIR=tmp_path), portfolio, [first, second])

    assert len(plans) == 1
    assert plans[0].symbol == "AAPL"
    assert plans[0].risk_decision.checks["duplicate_symbol_cycle_guard"]["blocked_additional_same_symbol_buys"] is True


def test_build_order_plans_expands_to_five_opportunistic_long_only_buys(tmp_path: Path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=100_000,
        portfolio_value=100_000,
        buying_power=100_000,
        positions=[],
        open_orders=[],
    )
    recommendations = [
        TradeRecommendation(
            symbol=f"SYM{i}",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            target_exposure_pct=0.05,
        )
        for i in range(5)
    ]

    plans = build_order_plans(Settings(DATA_DIR=tmp_path, MAX_ORDERS_PER_CYCLE=4), portfolio, recommendations)

    assert len(plans) == 5
    assert [plan.symbol for plan in plans] == [f"SYM{i}" for i in range(5)]


def test_deterministic_trade_fallback_allows_breakout_continuation_extension():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    candidate = _selection_candidate(
        "BBY",
        score=16,
        return_20d=0.29,
        close=126.18,
        sma_20=100.0,
        rsi_14=83.3,
        volume_zscore_20=1.79,
        close_position_in_range=0.994,
        breakout_continuation_long=True,
        breakout_failure_risk=False,
        chart_patterns=[
            {"bias": "bullish", "status": "confirmed"},
            {"bias": "bullish", "status": "confirmed"},
        ],
    )
    candidate["relative_return_20d"] = 0.23
    candidate["selection_score"] = 0.07
    candidate["selection_rank"] = 1
    context = {"selected_candidates": [candidate]}

    recommendations = deterministic_trade_fallback_recommendations(Settings(), portfolio, context)

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "BBY"
    assert recommendations[0].action == "buy"


def test_build_order_plans_blocks_existing_position_add_when_disabled():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AAPL",
                qty=10,
                market_value=500,
                avg_entry_price=90,
                current_price=100,
                unrealized_pl=100,
                unrealized_plpc=0.1,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="entrada adicional",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )

    plans = build_order_plans(Settings(ALLOW_POSITION_ADDS=False), portfolio, [recommendation])

    assert plans == []


def test_build_order_plans_allows_existing_position_add_when_enabled(tmp_path: Path):
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AAPL",
                qty=10,
                market_value=500,
                avg_entry_price=90,
                current_price=100,
                unrealized_pl=100,
                unrealized_plpc=0.1,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="entrada adicional",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )

    plans = build_order_plans(
        Settings(DATA_DIR=tmp_path, ALLOW_POSITION_ADDS=True),
        portfolio,
        [recommendation],
    )

    assert len(plans) == 1
    assert plans[0].symbol == "AAPL"


def test_build_order_plans_blocks_buys_when_operational_kill_switch_is_active(tmp_path: Path):
    settings = Settings(DATA_DIR=tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_operational_health.json").write_text(
        json.dumps(
            {
                "alerts": [
                    {
                        "severity": "critical",
                        "kind": "job_failed",
                        "job": "market_cycle",
                        "detail": "broker sync timeout",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )
    rejected = []

    plans = build_order_plans(settings, portfolio, [recommendation], rejected=rejected)

    assert plans == []
    assert rejected[0]["stage"] == "operational_kill_switch"


def test_build_order_plans_blocks_buys_when_market_state_is_partial_missing_context(tmp_path: Path):
    settings = Settings(DATA_DIR=tmp_path)
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )
    rejected = []

    plans = build_order_plans(
        settings,
        portfolio,
        [recommendation],
        rejected=rejected,
        market_state={
            "data_quality": {
                "status": "PARTIAL",
                "notes": ["macro_summary_missing", "sentiment_window_insufficient"],
                "data_vendor_quality": {"formal_provider": False, "severity": "WARN"},
            }
        },
    )

    assert plans == []
    assert rejected[0]["stage"] == "market_state_guard"
    assert rejected[0]["reason"] == "market_state_partial_missing_macro_or_news"


def test_build_order_plans_uses_existing_stop_data_for_aggregate_open_risk(tmp_path: Path):
    settings = Settings(DATA_DIR=tmp_path, MAX_TOTAL_OPEN_RISK=0.01)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="bo_aapl",
        plan_id="plan_aapl",
        cycle_id="cycle_1",
        symbol="AAPL",
        side="buy",
        status="filled",
        payload={
            "plan": {
                "symbol": "AAPL",
                "side": "buy",
                "notional": 5000.0,
                "payload": {
                    "entry_price": 100.0,
                    "stop_loss": 96.0,
                    "take_profit": 110.0,
                },
            }
        },
    )
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AAPL",
                qty=50,
                market_value=5000,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="MSFT",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )
    rejected = []

    plans = build_order_plans(settings, portfolio, [recommendation], rejected=rejected)

    assert plans == []
    assert rejected[0]["stage"] == "risk_manager"
    assert "riesgo agregado abierto" in rejected[0]["reason"]


def test_build_order_plans_can_exit_existing_long_position():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AAPL",
                qty=10,
                market_value=1000,
                avg_entry_price=90,
                current_price=100,
                unrealized_pl=100,
                unrealized_plpc=0.1,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="exit",
        confidence=0.9,
        reason="Stop loss tocado: soporte perdido.",
        stop_loss=105.0,
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].side == "sell"
    assert plans[0].qty == 10
    assert plans[0].risk_decision.approved


def test_build_order_plans_blocks_plain_rotation_exit():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AMZN",
                qty=10,
                market_value=1000,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AMZN",
        action="exit",
        confidence=0.9,
        reason="Rotacion: AMZN tiene menor score que PWR.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert plans == []


def test_selection_score_penalizes_known_negative_pockets():
    candidate = {
        "symbol": "WEAK",
        "direction": "long",
        "score": 16,
        "setup_quality": "strong",
        "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 112.0},
        "technical_state": {
            "close": 103.0,
            "sma_20": 100.0,
            "return_20d": 0.08,
            "return_60d": 0.10,
            "volume_zscore_20": -0.4,
            "rsi_14": 66.0,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed", "label": "doble suelo"}],
        },
    }

    base = _selection_score_for_candidate(
        candidate,
        {},
        {},
        settings=Settings(SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=False),
    )
    penalized = _selection_score_for_candidate(
        candidate,
        {},
        {},
        settings=Settings(SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=True),
    )

    assert penalized["selection_score"] < base["selection_score"]
    assert penalized["negative_pocket_penalty_total"] > 0
    assert penalized["negative_pocket_penalties"]["confirmed_pattern"] > 0
    assert penalized["negative_pocket_penalties"]["volume_z_lt0"] > 0
    assert penalized["negative_pocket_penalties"]["rsi_60_75"] > 0
    assert base["negative_pocket_penalty_total"] == 0
    assert base["negative_pocket_shadow_penalties"]["confirmed_pattern"] > 0
    assert base["negative_pocket_penalty_applied"] is False


def test_build_order_plans_allows_exceptional_bearish_exit():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AMZN",
                qty=10,
                market_value=900,
                avg_entry_price=100,
                current_price=90,
                unrealized_pl=-100,
                unrealized_plpc=-0.1,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AMZN",
        action="exit",
        confidence=0.95,
        reason="Deterioro bajista claro: soporte perdido y drawdown severo.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].side == "sell"


def test_build_order_plans_blocks_ordinary_llm_exit_even_with_small_drawdown():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="PWR",
                qty=10,
                market_value=997,
                avg_entry_price=100,
                current_price=99.7,
                unrealized_pl=-3,
                unrealized_plpc=-0.003,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="PWR",
        action="exit",
        confidence=0.95,
        reason="Posicion sin score tecnico valido y en drawdown. Liberar capital para oportunidades de alta calidad.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert plans == []


def test_build_order_plans_allows_material_negative_news_exit():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="XYZ",
                qty=10,
                market_value=1000,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="XYZ",
        action="exit",
        confidence=0.96,
        reason="Noticia negativa material: regulatory investigation and fraud risk.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].risk_decision.checks["exit_policy"]["trigger"] == "material_negative_event"


def test_build_order_plans_does_not_round_sell_qty_above_available():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AMZN",
                qty=13.600098938,
                market_value=3571.0,
                avg_entry_price=262.79,
                current_price=262.54,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AMZN",
        action="exit",
        confidence=0.9,
        reason="Stop loss tocado.",
        stop_loss=263.0,
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].qty == 13.600098938
    assert plans[0].qty <= portfolio.positions[0].qty


def _quality_recommendation(symbol="AAPL"):
    return TradeRecommendation(
        symbol=symbol,
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        target_exposure_pct=0.05,
    )


def _quality_context(**overrides):
    candidate = {
        "symbol": "AAPL",
        "direction": "long",
        "score": 14,
        "setup_quality": "strong",
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 95.0,
            "rsi_14": 72.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.5,
            "chart_patterns": [
                {"bias": "bullish", "status": "confirmed", "label": "doble suelo"},
            ],
        },
    }
    candidate.update(overrides)
    return {"top_longs": [candidate], "top_shorts": []}


def test_entry_quality_gate_approves_clean_strong_setup():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        _quality_recommendation(),
        _quality_context(),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["score"] == 14


def test_entry_quality_gate_blocks_missing_technical_candidate():
    approved, reason, _checks = validate_entry_quality(
        Settings(),
        _quality_recommendation(),
        {"top_longs": [], "top_shorts": []},
        {"results": []},
    )

    assert approved is False
    assert "ausente" in reason


def test_entry_quality_gate_blocks_overextended_sma20_distance(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            technical_state={
                "close": 120.0,
                "return_20d": 0.2,
                "sma_20": 100.0,
                "rsi_14": 78.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.0,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            }
        ),
        {"results": []},
    )

    assert approved is False
    assert "extendido" in reason
    assert checks["sma20_distance"] == 0.2


def test_entry_quality_gate_allows_fallback_momentum_extension(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="QCOM",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="QCOM",
            score=16,
            selection_rank=4,
            technical_state={
                "close": 128.0,
                "return_20d": 0.35,
                "sma_20": 100.0,
                "rsi_14": 83.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.0,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["sma20_distance"] == 0.28
    assert checks["fallback_momentum_extension_exception"]["eligible"] is True


def test_entry_quality_gate_blocks_fallback_momentum_extension_below_score_threshold(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="MCHP",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="MCHP",
            score=15,
            selection_rank=4,
            technical_state={
                "close": 122.0,
                "return_20d": 0.35,
                "sma_20": 100.0,
                "rsi_14": 83.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.0,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "extendido" in reason
    assert checks["fallback_momentum_extension_exception"]["eligible"] is False


def test_entry_quality_gate_allows_fallback_weak_volume_momentum_extension(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="AMD",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="AMD",
            score=15,
            selection_rank=8,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern",
            technical_state={
                "close": 118.0,
                "return_20d": 0.34,
                "sma_20": 100.0,
                "rsi_14": 76.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.1,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["fallback_weak_volume_momentum_extension_exception"]["eligible"] is True


def test_entry_quality_gate_blocks_weak_volume_momentum_extension_with_same_session_noise(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="JBL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="JBL",
            score=15,
            selection_rank=1,
            selection_reason=(
                "profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,"
                "same_session_intraday_momentum"
            ),
            technical_state={
                "close": 118.0,
                "return_20d": 0.34,
                "sma_20": 100.0,
                "rsi_14": 76.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.1,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "extendido" in reason
    assert checks["fallback_weak_volume_momentum_extension_exception"]["eligible"] is False


def test_entry_quality_gate_allows_relative_strength_pullback_extension(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="NTAP",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=106.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="NTAP",
            score=15,
            selection_rank=9,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,relative_strength",
            relative_return_20d=0.2601,
            technical_state={
                "close": 118.66,
                "return_20d": 0.313,
                "sma_20": 100.0,
                "rsi_14": 89.99,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.47,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["fallback_relative_strength_pullback_extension_exception"]["eligible"] is True
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["mode"] == "relative_strength_pullback_extension"


def test_entry_quality_gate_blocks_relative_strength_pullback_outside_return_band(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="CRWD",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="CRWD",
            score=15,
            selection_rank=7,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,relative_strength",
            relative_return_20d=0.3135,
            technical_state={
                "close": 118.66,
                "return_20d": 0.3754,
                "sma_20": 100.0,
                "rsi_14": 88.62,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.72,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "extendido" in reason
    assert checks["fallback_relative_strength_pullback_extension_exception"]["eligible"] is False


def test_entry_quality_gate_allows_leader_pullback_extension(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="DELL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="DELL",
            score=15,
            selection_rank=4,
            selection_reason=(
                "profile_edge_high_sample,confirmed_pattern,leader_momentum_extension,"
                "relative_strength,weak_volume_tolerated_for_leader"
            ),
            relative_return_20d=0.37,
            technical_state={
                "close": 127.14,
                "return_20d": 0.4269,
                "sma_20": 100.0,
                "rsi_14": 78.6,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.35,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["fallback_leader_pullback_extension_exception"]["eligible"] is True


def test_entry_quality_gate_blocks_leader_pullback_outside_return_band(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="HPQ",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="HPQ",
            score=15,
            selection_rank=4,
            selection_reason=(
                "profile_edge_high_sample,confirmed_pattern,leader_momentum_extension,"
                "relative_strength,weak_volume_tolerated_for_leader"
            ),
            relative_return_20d=0.22,
            technical_state={
                "close": 127.14,
                "return_20d": 0.32,
                "sma_20": 100.0,
                "rsi_14": 78.6,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.35,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "extendido" in reason
    assert checks["fallback_leader_pullback_extension_exception"]["eligible"] is False


def test_entry_quality_gate_allows_top_long_follow_through_without_relative_strength(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="CSCO",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=104.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="CSCO",
            score=15,
            selection_rank=17,
            selection_reason=(
                "profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,top_long_alignment"
            ),
            relative_return_20d=None,
            technical_state={
                "close": 116.0,
                "return_20d": 0.165,
                "sma_20": 100.0,
                "rsi_14": 70.1,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.2,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["fallback_top_long_follow_through_exception"]["eligible"] is True
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["mode"] == "top_long_follow_through"


def test_entry_quality_gate_blocks_top_long_follow_through_without_alignment(tmp_path):
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="GLW",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=104.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="GLW",
            score=15,
            selection_rank=17,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern",
            relative_return_20d=None,
            technical_state={
                "close": 116.0,
                "return_20d": 0.165,
                "sma_20": 100.0,
                "rsi_14": 70.1,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.2,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "entry_score_v2 bajo" in reason
    assert checks["fallback_top_long_follow_through_exception"]["eligible"] is False


def test_entry_quality_gate_allows_weak_volume_momentum_despite_prior_error(tmp_path):
    candidate = _quality_context(
        symbol="AMD",
        score=15,
        selection_rank=8,
        selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern",
        technical_state={
            "close": 118.0,
            "return_20d": 0.34,
            "sma_20": 100.0,
            "rsi_14": 76.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": -1.1,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )["top_longs"][0]
    features = _candidate_learning_features(candidate)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.01, "win_rate": 0.5, "matured": 10}],
                "setup_priors_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "expected_edge": 0.015,
                        "win_rate": 0.45,
                        "matured": 8,
                        "confidence_weight": 1.0,
                    }
                ],
                "prior_accuracy_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "matured": 8,
                        "avg_abs_error": 0.08,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="AMD",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["prior_accuracy"]["avg_abs_error"] == 0.08
    assert checks["fallback_weak_volume_momentum_extension_exception"]["eligible"] is True


def test_entry_quality_gate_keeps_prior_error_block_without_weak_volume_momentum_exception(tmp_path):
    candidate = _quality_context(
        symbol="JBL",
        score=15,
        selection_rank=1,
        selection_reason=(
            "profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,"
            "same_session_intraday_momentum"
        ),
        technical_state={
            "close": 118.0,
            "return_20d": 0.34,
            "sma_20": 100.0,
            "rsi_14": 76.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": -1.1,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )["top_longs"][0]
    features = _candidate_learning_features(candidate)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.01, "win_rate": 0.5, "matured": 10}],
                "setup_priors_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "expected_edge": 0.015,
                        "win_rate": 0.45,
                        "matured": 8,
                        "confidence_weight": 1.0,
                    }
                ],
                "prior_accuracy_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "matured": 8,
                        "avg_abs_error": 0.08,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        TradeRecommendation(
            symbol="JBL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is False
    assert reason == "perfil reciente sobreestima el edge con demasiada frecuencia"
    assert checks["fallback_weak_volume_momentum_extension_exception"]["eligible"] is False


def test_entry_quality_gate_allows_prior_error_volume_confirmation_override(tmp_path):
    candidate = _quality_context(
        symbol="FTNT",
        score=16,
        selection_rank=4,
        selection_reason="profile_edge_high_sample,volume_confirmation,confirmed_pattern",
        technical_state={
            "close": 118.0,
            "return_20d": 0.34,
            "sma_20": 100.0,
            "rsi_14": 84.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 2.8,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )["top_longs"][0]
    features = _candidate_learning_features(candidate)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.01, "win_rate": 0.5, "matured": 10}],
                "setup_priors_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "expected_edge": 0.015,
                        "win_rate": 0.45,
                        "matured": 8,
                        "confidence_weight": 1.0,
                    }
                ],
                "prior_accuracy_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "matured": 8,
                        "avg_abs_error": 0.08,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.35),
        TradeRecommendation(
            symbol="FTNT",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["prior_error_volume_confirmation_override_exception"]["eligible"] is True


def test_entry_quality_gate_keeps_prior_error_block_without_volume_confirmation_override(tmp_path):
    candidate = _quality_context(
        symbol="HWM",
        score=15,
        selection_rank=13,
        selection_reason="profile_edge_high_sample,volume_confirmation,confirmed_pattern",
        technical_state={
            "close": 106.0,
            "return_20d": 0.06,
            "sma_20": 100.0,
            "rsi_14": 59.7,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.7,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )["top_longs"][0]
    features = _candidate_learning_features(candidate)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.01, "win_rate": 0.5, "matured": 10}],
                "setup_priors_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "expected_edge": 0.015,
                        "win_rate": 0.45,
                        "matured": 8,
                        "confidence_weight": 1.0,
                    }
                ],
                "prior_accuracy_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "matured": 8,
                        "avg_abs_error": 0.08,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.35),
        TradeRecommendation(
            symbol="HWM",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is False
    assert reason == "perfil reciente sobreestima el edge con demasiada frecuencia"
    assert checks["prior_error_volume_confirmation_override_exception"]["eligible"] is False


def test_entry_quality_gate_routes_overextended_breakout_continuation_to_specific_exception():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=17,
            relative_return_20d=0.24,
            technical_state={
                "close": 120.0,
                "return_20d": 0.28,
                "sma_20": 100.0,
                "rsi_14": 80.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.2,
                "close_position_in_range": 0.88,
                "breakout_continuation_long": True,
                "chart_patterns": [
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert reason == "breakout continuation sin volumen relativo suficiente"
    assert checks["breakout_continuation_exception"]["min_volume_zscore_20"] == 1.5


def test_entry_quality_gate_allows_confirmed_event_momentum_extension():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=18,
            technical_state={
                "close": 134.0,
                "return_20d": 0.6,
                "sma_20": 103.0,
                "rsi_14": 87.0,
                "macd": 5.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 3.5,
                "gap_pct": 0.24,
                "close_position_in_range": 0.88,
                "event_momentum_long": True,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["event_momentum_exception"]["min_volume_zscore_20"] == 2.0


def test_entry_quality_gate_blocks_event_momentum_without_strong_close():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=18,
            technical_state={
                "close": 134.0,
                "return_20d": 0.6,
                "sma_20": 103.0,
                "rsi_14": 87.0,
                "macd": 5.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 3.5,
                "event_momentum_long": True,
                "close_position_in_range": 0.4,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "cierre firme" in reason
    assert checks["event_momentum_long"] is True


def test_entry_quality_gate_blocks_range_expansion_breakout_without_required_volume():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=17,
            relative_return_20d=0.08,
            technical_state={
                "close": 117.0,
                "return_20d": 0.18,
                "sma_20": 100.0,
                "rsi_14": 67.0,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.2,
                "gap_pct": 0.05,
                "close_position_in_range": 0.82,
                "range_expansion_breakout_long": True,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert reason == "range_expansion_breakout_shadow_only"
    assert checks["shadow_only_setup"] == "range_expansion_breakout"
    assert checks["range_expansion_breakout_exception"]["eligible"] is False


def test_entry_quality_gate_allows_range_expansion_breakout_in_opportunistic_paper():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=17,
            relative_return_20d=0.08,
            technical_state={
                "close": 117.0,
                "return_20d": 0.18,
                "sma_20": 100.0,
                "rsi_14": 78.0,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.3,
                "gap_pct": 0.05,
                "close_position_in_range": 0.82,
                "range_expansion_breakout_long": True,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["range_expansion_breakout_exception"]["eligible"] is True


def test_entry_quality_gate_blocks_range_expansion_with_extreme_rsi():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=17,
            relative_return_20d=0.08,
            technical_state={
                "close": 117.0,
                "return_20d": 0.18,
                "sma_20": 100.0,
                "rsi_14": 83.0,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.3,
                "gap_pct": 0.05,
                "close_position_in_range": 0.82,
                "range_expansion_breakout_long": True,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert reason == "range_expansion_breakout_shadow_only"
    assert checks["range_expansion_breakout_long"] is True


def test_entry_quality_gate_allows_orderly_breakout_extension():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=14,
            relative_return_20d=0.06,
            technical_state={
                "close": 121.0,
                "return_20d": 0.14,
                "sma_20": 100.0,
                "rsi_14": 69.0,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.4,
                "close_position_in_range": 0.84,
                "orderly_breakout_long": True,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["orderly_breakout_exception"]["max_rsi"] == 74.0
    assert checks["orderly_breakout_exception"]["min_score"] == 14


def test_entry_quality_gate_allows_breakout_continuation_extension():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=16,
            relative_return_20d=0.23,
            technical_state={
                "close": 126.18,
                "return_20d": 0.29,
                "sma_20": 100.0,
                "rsi_14": 83.3,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.79,
                "close_position_in_range": 0.994,
                "breakout_continuation_long": True,
                "breakout_failure_risk": False,
                "chart_patterns": [
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["breakout_continuation_exception"]["max_sma20_distance"] == 0.27
    assert checks["breakout_continuation_exception"]["min_score"] == 16


def test_entry_quality_gate_blocks_breakout_continuation_without_exceptional_close():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=16,
            relative_return_20d=0.23,
            technical_state={
                "close": 126.18,
                "return_20d": 0.29,
                "sma_20": 100.0,
                "rsi_14": 83.3,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.79,
                "close_position_in_range": 0.84,
                "breakout_continuation_long": True,
                "breakout_failure_risk": False,
                "chart_patterns": [
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "cierre excepcionalmente fuerte" in reason
    assert checks["breakout_continuation_long"] is True


def test_entry_quality_gate_blocks_orderly_breakout_with_extreme_rsi():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=16,
            relative_return_20d=0.06,
            technical_state={
                "close": 121.0,
                "return_20d": 0.14,
                "sma_20": 100.0,
                "rsi_14": 78.0,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.4,
                "close_position_in_range": 0.84,
                "orderly_breakout_long": True,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "RSI demasiado extremo" in reason
    assert checks["orderly_breakout_long"] is True


def test_entry_quality_gate_allows_momentum_shakeout_extension():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=15,
            technical_state={
                "close": 116.0,
                "return_20d": 0.06,
                "sma_20": 100.0,
                "rsi_14": 77.0,
                "macd": 2.5,
                "macd_signal": -0.2,
                "volume_zscore_20": 1.7,
                "gap_pct": -0.04,
                "close_position_in_range": 0.86,
                "momentum_shakeout_hold_long": True,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["momentum_shakeout_exception"]["max_sma20_distance"] == 0.20


def test_entry_quality_gate_allows_confirmed_momentum_extension():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=16,
            relative_return_20d=0.07,
            technical_state={
                "close": 120.6,
                "return_20d": 0.34,
                "sma_20": 100.0,
                "rsi_14": 81.6,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 3.4,
                "close_position_in_range": 0.96,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["momentum_confirmation_long"] is True
    assert checks["momentum_confirmation_exception"]["max_rsi"] == 88.0


def test_entry_quality_gate_blocks_confirmed_momentum_with_extreme_rsi():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            score=16,
            relative_return_20d=0.07,
            technical_state={
                "close": 120.6,
                "return_20d": 0.34,
                "sma_20": 100.0,
                "rsi_14": 88.5,
                "macd": 4.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 3.4,
                "close_position_in_range": 0.96,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "RSI demasiado extremo" in reason
    assert checks["momentum_confirmation_long"] is True


def test_entry_quality_gate_blocks_extended_entry_without_relative_strength(tmp_path):
    approved, reason, _checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE=0.08),
        _quality_recommendation(),
        _quality_context(
            technical_state={
                "close": 109.0,
                "return_20d": 0.2,
                "sma_20": 100.0,
                "rsi_14": 78.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.5,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            }
        ),
        {"results": []},
    )

    assert approved is False
    assert "fuerza relativa" in reason


def test_entry_quality_gate_allows_extended_entry_with_confirmations(tmp_path):
    context = _quality_context(
        relative_return_20d=0.04,
        technical_state={
            "close": 109.0,
            "return_20d": 0.2,
            "sma_20": 100.0,
            "rsi_14": 78.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.8,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )

    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE=0.08),
        _quality_recommendation(),
        context,
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["extended_entry_filter"]["min_relative_return_20d"] == 0.02


def test_entry_quality_gate_allows_confirmed_breakout_when_relative_strength_missing(tmp_path):
    context = _quality_context(
        score=18,
        technical_state={
            "close": 111.1,
            "return_20d": 0.31,
            "sma_20": 100.0,
            "rsi_14": 72.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.01,
            "close_position_in_range": 0.98,
            "orderly_breakout_long": True,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )

    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE=0.08),
        _quality_recommendation(),
        context,
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["relative_return_20d"] is None
    assert checks["relative_strength_missing_exception"]["allowed"] is True


def test_entry_quality_gate_allows_confirmed_momentum_when_relative_strength_missing(tmp_path):
    context = _quality_context(
        score=18,
        technical_state={
            "close": 111.1,
            "return_20d": 0.31,
            "sma_20": 100.0,
            "rsi_14": 72.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.01,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )

    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path, ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE=0.08),
        _quality_recommendation(),
        context,
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["relative_return_20d"] is None
    assert checks["relative_strength_missing_exception"]["allowed"] is True
    assert checks["relative_strength_missing_exception"]["reason"] == "confirmed_momentum_with_volume_and_pattern"
    assert checks["relative_strength_missing_exception"]["confirmed_momentum_exception"]["allowed"] is True


def test_entry_quality_gate_blocks_negative_confirmed_sentiment():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        _quality_recommendation(),
        _quality_context(),
        {
            "results": [
                {
                    "symbol": "AAPL",
                    "sentiment": {"sentiment_score": -0.8, "confidence": 0.7},
                }
            ]
        },
    )

    assert approved is False
    assert "sentimiento negativo" in reason
    assert checks["sentiment_score"] == -0.8


def test_entry_quality_gate_penalizes_sentiment_failure_by_default():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        _quality_recommendation(),
        _quality_context(),
        {
            "results": [
                {
                    "symbol": "AAPL",
                    "sentiment": {"risk_flags": ["sentiment_failed"]},
                }
            ]
        },
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["sentiment_flags"] == ["sentiment_failed"]
    assert checks["sentiment_data_quality"]["status"] == "missing_or_failed"
    assert checks["entry_score_v2"]["missing_data"]["sentiment"] is True
    assert checks["entry_score_v2"]["missing_data_penalty"] == 0.03
    assert "sentimiento_no_validado_penalizado" in checks["entry_score_v2"]["reasons"]


def test_filter_entry_quality_keeps_entry_score_micro_experiment():
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=107.5,
        target_exposure_pct=0.05,
    )
    context = _quality_context(
        score=10,
        technical_state={
            "close": 100.0,
            "return_20d": 0.03,
            "sma_20": 98.0,
            "rsi_14": 70.0,
            "macd": 1.0,
            "macd_signal": 0.5,
            "volume_zscore_20": 0.0,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )

    kept, decisions = filter_entry_quality(
        Settings(ENTRY_QUALITY_MIN_SCORE=10, ENTRY_SCORE_V2_MIN=0.65),
        [recommendation],
        context,
        {
            "results": [
                {
                    "symbol": "AAPL",
                    "sentiment": {"risk_flags": ["sentiment_failed"]},
                }
            ]
        },
    )

    assert len(kept) == 1
    assert kept[0].micro_experiment is True
    assert kept[0].size_multiplier == 0.5
    assert "entry_score_v2_micro_experiment" in kept[0].soft_override_reasons
    assert decisions[0]["checks"]["entry_score_v2"]["micro_experiment"] is True


def test_entry_quality_gate_can_fail_closed_on_sentiment_failure():
    approved, reason, checks = validate_entry_quality(
        Settings(NEWS_SENTIMENT_FAIL_CLOSED_FOR_BUYS=True),
        _quality_recommendation(),
        _quality_context(),
        {
            "results": [
                {
                    "symbol": "AAPL",
                    "sentiment": {"risk_flags": ["sentiment_failed"]},
                }
            ]
        },
    )

    assert approved is False
    assert "sentimiento no validado" in reason
    assert checks["sentiment_flags"] == ["sentiment_failed"]
    assert checks["sentiment_data_quality"]["status"] == "missing_or_failed"


def test_entry_quality_gate_allows_sentiment_failure_for_deterministic_fallback():
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        target_exposure_pct=0.05,
        source="deterministic_fallback",
    )

    approved, reason, checks = validate_entry_quality(
        Settings(),
        recommendation,
        _quality_context(),
        {
            "results": [
                {
                    "symbol": "AAPL",
                    "sentiment": {"risk_flags": ["sentiment_failed"]},
                }
            ]
        },
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["sentiment_flags"] == ["sentiment_failed"]
    assert checks["deterministic_fallback"] is True


def test_entry_quality_gate_blocks_low_reward_risk_v2():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=106.0,
            target_exposure_pct=0.05,
        ),
        _quality_context(),
        {"results": []},
    )

    assert approved is False
    assert "entry_score_v2" in reason
    assert checks["entry_score_v2"]["reward_risk"] == 1.2
    assert "reward_risk_bajo" in checks["entry_score_v2"]["hard_blocks"]


def test_entry_quality_gate_allows_marginal_reward_risk_for_high_conviction_deterministic_fallback():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=107.49,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            score=14,
            selection_rank=3,
            relative_return_20d=0.12,
            technical_state={
                "close": 100.0,
                "return_20d": 0.24,
                "sma_20": 91.0,
                "rsi_14": 76.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.5,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["applied"] is True
    assert checks["entry_score_v2"]["hard_blocks"] == []


def test_entry_quality_gate_keeps_blocking_marginal_reward_risk_without_high_conviction_rank():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=107.49,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            score=14,
            selection_rank=12,
            relative_return_20d=0.12,
            technical_state={
                "close": 100.0,
                "return_20d": 0.24,
                "sma_20": 91.0,
                "rsi_14": 76.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.5,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "entry_score_v2" in reason
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["applied"] is False
    assert "reward_risk_bajo" in checks["entry_score_v2"]["hard_blocks"]


def test_entry_quality_gate_allows_follow_through_reward_risk_override_for_constructive_pattern():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=107.49,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            score=15,
            selection_rank=12,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,constructive_early_pattern",
            technical_state={
                "close": 100.0,
                "return_20d": 0.069,
                "sma_20": 93.0,
                "rsi_14": 71.2,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.8,
                "chart_patterns": [
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["applied"] is True
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["mode"] == "follow_through_pattern"
    assert checks["entry_score_v2"]["hard_blocks"] == []


def test_entry_quality_gate_keeps_blocking_follow_through_reward_risk_when_alignment_is_noisy():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=107.49,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            score=16,
            selection_rank=11,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,top_long_alignment",
            technical_state={
                "close": 100.0,
                "return_20d": 0.11,
                "sma_20": 94.5,
                "rsi_14": 66.3,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -2.6,
                "chart_patterns": [
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "entry_score_v2" in reason
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["applied"] is False
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["mode"] is None
    assert "reward_risk_bajo" in checks["entry_score_v2"]["hard_blocks"]


def test_entry_quality_gate_allows_late_constructive_follow_through_reward_risk_override():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="FTNT",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=107.49,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="FTNT",
            score=14,
            selection_rank=18,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,constructive_early_pattern",
            technical_state={
                "close": 100.0,
                "return_20d": 0.0667,
                "sma_20": 94.0,
                "rsi_14": 65.36,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.84,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["applied"] is True
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["mode"] == "late_constructive_follow_through"
    assert checks["entry_score_v2"]["hard_blocks"] == []


def test_entry_quality_gate_blocks_late_constructive_follow_through_with_unfiltered_volume():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="GWW",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=107.49,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="GWW",
            score=15,
            selection_rank=18,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,constructive_early_pattern",
            technical_state={
                "close": 100.0,
                "return_20d": 0.0741,
                "sma_20": 94.0,
                "rsi_14": 70.14,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.46,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert "entry_score_v2" in reason
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["applied"] is False
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["mode"] is None
    assert "reward_risk_bajo" in checks["entry_score_v2"]["hard_blocks"]


def test_entry_quality_gate_allows_low_score_volume_rebound_reward_risk_override():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="COHR",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=107.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            symbol="COHR",
            score=8,
            selection_rank=4,
            selection_reason="profile_edge_shrunk,volume_confirmation",
            technical_state={
                "close": 100.0,
                "return_20d": 0.1177,
                "sma_20": 95.0,
                "rsi_14": 39.22,
                "macd": 0.8,
                "macd_signal": 1.0,
                "volume_zscore_20": 2.9,
                "chart_patterns": [],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["low_score_volume_rebound_override_exception"]["eligible"] is True
    assert checks["entry_score_v2"]["reward_risk_margin_override"]["mode"] == "low_score_volume_rebound"
    assert checks["entry_score_v2"]["hard_blocks"] == []


def test_entry_quality_gate_allows_missing_relative_strength_follow_through_alignment():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            score=16,
            selection_rank=12,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,top_long_alignment",
            technical_state={
                "close": 100.0,
                "return_20d": 0.176,
                "sma_20": 92.0,
                "rsi_14": 68.6,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -2.4,
                "chart_patterns": [
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["relative_strength_missing_exception"]["allowed"] is True
    assert checks["relative_strength_missing_exception"]["reason"] == "follow_through_alignment_without_relative_strength"
    assert checks["relative_strength_missing_exception"]["follow_through_exception"]["allowed"] is True


def test_entry_quality_gate_keeps_blocking_missing_relative_strength_without_alignment_exception():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            score=16,
            selection_rank=12,
            selection_reason="profile_edge_high_sample,weak_volume_penalty,confirmed_pattern",
            technical_state={
                "close": 100.0,
                "return_20d": 0.176,
                "sma_20": 92.0,
                "rsi_14": 68.6,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -2.4,
                "chart_patterns": [
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            },
        ),
        {"results": []},
    )

    assert approved is False
    assert reason == "entrada extendida sin fuerza relativa 20d disponible"
    assert checks["relative_strength_missing_exception"]["allowed"] is False
    assert checks["relative_strength_missing_exception"]["follow_through_exception"]["allowed"] is False


def test_entry_quality_gate_allows_constructive_extension_for_deterministic_fallback(tmp_path):
    # DATA_DIR aislado: el test no debe depender de los priors del data/ vivo.
    approved, reason, checks = validate_entry_quality(
        Settings(DATA_DIR=tmp_path),
        TradeRecommendation(
            symbol="AAPL",
            action="buy",
            confidence=0.9,
            reason="test",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            target_exposure_pct=0.05,
            source="deterministic_fallback",
        ),
        _quality_context(
            score=13,
            selection_rank=3,
            technical_state={
                "close": 112.08,
                "return_20d": 0.2322,
                "sma_20": 100.0,
                "rsi_14": 74.12,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.83,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
        ),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["fallback_constructive_extension_exception"]["eligible"] is True


def test_annotate_technical_context_with_learning_adds_setup_edge_and_penalty():
    technical_context = {
        "top_longs": [
            {
                "symbol": "EDGE",
                "score": 15,
                "technical_state": {"event_momentum_long": True, "return_20d": 0.25, "volume_zscore_20": 3.0},
            },
            {
                "symbol": "BASE",
                "score": 17,
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.1, "chart_patterns": []},
            },
        ]
    }
    daily_learning_digest = {
        "setup_stats_3d": [
            {"setup": "event_momentum", "avg_return": 0.08, "win_rate": 0.75, "matured": 8},
            {"setup": "baseline_trend", "avg_return": 0.01, "win_rate": 0.45, "matured": 12},
        ]
    }
    operational_context = {
        "responses": [
            {
                "status": "guarded_active",
                "action": "deprioritize_setup_before_llm",
                "scope": "baseline_trend",
                "candidate_priority_penalty": 0.05,
                "detail": "baseline_trend degradado",
            }
        ],
        "setup_penalties": {"baseline_trend": 0.05},
        "response_notes": {"baseline_trend": ["baseline_trend degradado"]},
    }

    annotated = _annotate_technical_context_with_learning(
        technical_context,
        daily_learning_digest,
        operational_context,
    )

    assert annotated["top_longs"][0]["setup_name"] == "event_momentum"
    assert annotated["top_longs"][0]["effective_setup_edge_3d"] == 0.08
    assert annotated["top_longs"][1]["setup_name"] == "baseline_trend"
    assert annotated["top_longs"][1]["operational_penalty"] == 0.05
    assert annotated["top_longs"][1]["effective_setup_edge_3d"] == -0.04
    assert annotated["top_longs"][1]["operational_notes"] == ["baseline_trend degradado"]


def test_build_decision_learning_context_surfaces_guidance_and_active_responses():
    daily_learning_digest = {
        "summary": {"executed_observations": 12},
        "guidance": ["Priorizar setups con edge 3d positivo.", "Evitar duplicados intradia."],
        "setup_stats_3d": [
            {"setup": "event_momentum", "avg_return": 0.08, "win_rate": 0.75},
            {"setup": "baseline_trend", "avg_return": -0.02, "win_rate": 0.25},
        ],
    }
    operational_context = {
        "responses": [
            {
                "status": "guarded_active",
                "action": "deprioritize_setup_before_llm",
                "scope": "baseline_trend",
                "detail": "Reducir prioridad del setup baseline_trend.",
                "mode": "ranking_only",
            },
            {
                "status": "shadow",
                "action": "pause_recent_universe_overlays",
                "scope": "technical_study",
                "detail": "Solo shadow",
                "mode": "shadow_only",
            },
        ]
    }

    context = _build_decision_learning_context(daily_learning_digest, operational_context)

    assert context["guidance"] == ["Priorizar setups con edge 3d positivo.", "Evitar duplicados intradia."]
    assert context["top_setups_3d"][0]["setup"] == "event_momentum"
    assert context["weak_setups_3d"][0]["setup"] == "baseline_trend"
    assert context["active_operational_responses"] == [
        {
            "action": "deprioritize_setup_before_llm",
            "scope": "baseline_trend",
            "detail": "Reducir prioridad del setup baseline_trend.",
            "mode": "ranking_only",
        }
    ]


def test_candidate_learning_prior_prefers_profile_and_applies_penalty():
    candidate = {
        "symbol": "BASE",
        "score": 17,
        "technical_state": {
            "close": 100.0,
            "sma_20": 95.0,
            "rsi_14": 72.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.1,
            "return_20d": 0.05,
            "chart_patterns": [],
        },
    }
    features = _candidate_learning_features(candidate)
    digest = {
        "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.01, "win_rate": 0.45, "matured": 12}],
        "setup_priors_3d": [
            {
                "profile_key": _prior_profile_key(features),
                "setup": "baseline_trend",
                "expected_edge": 0.03,
                "win_rate": 0.6,
                "matured": 8,
                "confidence_weight": 1.0,
            }
        ],
    }
    operational_context = {"setup_penalties": {"baseline_trend": 0.05}}

    prior = _candidate_learning_prior(candidate, digest, operational_context)

    assert prior["matched_on"] == "profile"
    assert prior["expected_edge_3d"] == -0.02
    assert prior["sample_size_3d"] == 8
    assert prior["confidence_weight_3d"] == 1.0


def test_annotate_technical_context_ranks_recent_edge_above_raw_score():
    strong = {
        "symbol": "STRONG",
        "direction": "long",
        "score": 14,
        "setup_quality": "strong",
        "relative_return_20d": 0.12,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 95.0,
            "rsi_14": 70.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.3,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed", "label": "breakout"}],
        },
    }
    weak = {
        "symbol": "WEAK",
        "direction": "long",
        "score": 18,
        "setup_quality": "strong",
        "relative_return_20d": 0.01,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.04,
            "sma_20": 96.0,
            "rsi_14": 66.0,
            "macd": 1.8,
            "macd_signal": 1.0,
            "volume_zscore_20": -0.3,
            "chart_patterns": [],
        },
    }
    strong_key = _prior_profile_key(_candidate_learning_features(strong))
    weak_key = _prior_profile_key(_candidate_learning_features(weak))
    digest = {
        "setup_stats_3d": [{"setup": "confirmed_pattern", "avg_return": 0.02, "win_rate": 0.6, "matured": 12}],
        "setup_priors_3d": [
            {"profile_key": strong_key, "setup": "confirmed_pattern", "expected_edge": 0.03, "win_rate": 0.65, "matured": 8, "confidence_weight": 1.0},
            {"profile_key": weak_key, "setup": "baseline_trend", "expected_edge": 0.005, "win_rate": 0.45, "matured": 8, "confidence_weight": 1.0},
        ],
        "prior_accuracy_3d": [
            {"profile_key": strong_key, "avg_abs_error": 0.01, "matured": 7},
            {"profile_key": weak_key, "avg_abs_error": 0.05, "matured": 7},
        ],
    }

    annotated = _annotate_technical_context_with_learning(
        {"top_longs": [weak, strong], "top_shorts": [], "selected_candidates": [weak, strong]},
        digest,
        {},
    )

    assert annotated["top_longs"][0]["symbol"] == "STRONG"
    assert annotated["selected_candidates"][0]["symbol"] == "STRONG"


def test_deterministic_reviewer_blocks_negative_sentiment_and_degrades_partial_market_state():
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )
    context = _quality_context(score=16)
    partial_state = {
        "market_regime": "neutral",
        "data_quality": {"status": "PARTIAL", "notes": ["macro_summary_missing"]},
    }

    reviewed, decisions = review_recommendations(
        Settings(),
        [recommendation],
        context,
        {
            "results": [
                {
                    "symbol": "AAPL",
                    "material_risk": False,
                    "sentiment": {"sentiment_score": -0.8},
                }
            ]
        },
        partial_state,
    )

    assert reviewed[0].symbol == "AAPL"
    assert decisions[0]["approved"] is False
    assert decisions[0]["reason"] == "sentimiento_negativo_material"

    reviewed, decisions = review_recommendations(
        Settings(),
        [recommendation],
        context,
        {"results": []},
        partial_state,
    )

    assert decisions[0]["approved"] is True
    assert reviewed[0].micro_experiment is True
    assert decisions[0]["reason"] == "micro_experiment_required"


def test_adversarial_reviewer_blocks_lookahead_and_regime_halt():
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )
    decisions = review_recommendations_adversarial(
        [recommendation],
        technical_context={"selected_candidates": [{"symbol": "AAPL", "future_data_used": True}]},
        market_state={
            "data_quality": {"status": "INSUFFICIENT"},
            "market_regime_policy": {"allow_new_buys": False, "requires_micro_experiment": False},
        },
    )

    assert decisions[0]["approved"] is False
    assert {item["kind"] for item in decisions[0]["issues"]} >= {
        "potential_lookahead_bias",
        "insufficient_market_state",
        "regime_policy_blocks_new_buys",
    }


def test_annotate_technical_context_rewards_breakout_follow_through():
    breakout = {
        "symbol": "BRK",
        "direction": "long",
        "score": 14,
        "setup_quality": "strong",
        "relative_return_20d": 0.08,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 95.0,
            "rsi_14": 68.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.2,
            "breakout_continuation_long": True,
            "breakout_failure_risk": False,
            "chart_patterns": [],
        },
    }
    failing = {
        "symbol": "FAIL",
        "direction": "long",
        "score": 15,
        "setup_quality": "strong",
        "relative_return_20d": 0.08,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 95.0,
            "rsi_14": 68.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.2,
            "breakout_continuation_long": False,
            "breakout_failure_risk": True,
            "chart_patterns": [],
        },
    }

    annotated = _annotate_technical_context_with_learning(
        {"top_longs": [failing, breakout], "top_shorts": [], "selected_candidates": [failing, breakout]},
        {},
        {},
    )

    assert annotated["top_longs"][0]["symbol"] == "BRK"
    assert "breakout_follow_through" in annotated["top_longs"][0]["rank_priority_reason"]
    assert "breakout_failure_penalty" in annotated["top_longs"][1]["rank_priority_reason"]


def test_annotate_technical_context_promotes_leader_momentum_extension():
    leader = {
        "symbol": "SNDK",
        "direction": "long",
        "score": 15,
        "setup_quality": "strong",
        "relative_return_20d": 0.22,
        "technical_state": {
            "close": 118.0,
            "return_20d": 0.22,
            "sma_20": 100.0,
            "rsi_14": 64.0,
            "macd": 2.3,
            "macd_signal": 1.0,
            "volume_zscore_20": -0.3,
            "close_position_in_range": 0.88,
            "chart_patterns": [
                {"bias": "bullish", "status": "confirmed", "label": "hch invertido"},
                {"bias": "bullish", "status": "confirmed", "label": "doble suelo"},
            ],
        },
    }
    plain = {
        "symbol": "PLAIN",
        "direction": "long",
        "score": 17,
        "setup_quality": "strong",
        "relative_return_20d": 0.04,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.04,
            "sma_20": 97.0,
            "rsi_14": 67.0,
            "macd": 1.8,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.1,
            "close_position_in_range": 0.62,
            "chart_patterns": [],
        },
    }

    annotated = _annotate_technical_context_with_learning(
        {"top_longs": [plain, leader], "top_shorts": [], "selected_candidates": [plain, leader]},
        {},
        {},
    )

    assert annotated["top_longs"][0]["symbol"] == "SNDK"
    assert "leader_momentum_extension" in annotated["top_longs"][0]["rank_priority_reason"]
    assert annotated["top_longs"][0]["rank_priority_components"]["leader_momentum_extension_component"] > 0


def test_annotate_technical_context_promotes_relaxed_leader_momentum_extension():
    leader = {
        "symbol": "SNDK",
        "direction": "long",
        "score": 11,
        "setup_quality": "strong",
        "relative_return_20d": 0.24,
        "technical_state": {
            "close": 133.0,
            "return_20d": 0.34,
            "sma_20": 100.0,
            "rsi_14": 69.8,
            "macd": 2.1,
            "macd_signal": 1.0,
            "volume_zscore_20": -1.8,
            "close_position_in_range": 0.4,
            "chart_patterns": [
                {"bias": "bullish", "status": "confirmed", "label": "hch invertido"},
            ],
        },
    }
    plain = {
        "symbol": "PLAIN",
        "direction": "long",
        "score": 15,
        "setup_quality": "strong",
        "relative_return_20d": 0.03,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.03,
            "sma_20": 98.0,
            "rsi_14": 63.0,
            "macd": 1.1,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.0,
            "close_position_in_range": 0.61,
            "chart_patterns": [],
        },
    }

    annotated = _annotate_technical_context_with_learning(
        {"top_longs": [plain, leader], "top_shorts": [], "selected_candidates": [plain, leader]},
        {},
        {},
    )

    assert annotated["top_longs"][0]["symbol"] == "SNDK"
    assert "leader_momentum_extension" in annotated["top_longs"][0]["rank_priority_reason"]
    assert annotated["top_longs"][0]["rank_priority_components"]["leader_momentum_extension_component"] > 0


def test_annotate_technical_context_promotes_emerging_leader_momentum():
    emerging = {
        "symbol": "QCOM",
        "direction": "long",
        "score": 11,
        "setup_quality": "strong",
        "technical_state": {
            "close": 110.0,
            "return_20d": 0.16,
            "sma_20": 100.0,
            "rsi_14": 76.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.2,
            "close_position_in_range": 0.86,
            "chart_patterns": [],
        },
    }
    plain = {
        "symbol": "PLAIN",
        "direction": "long",
        "score": 15,
        "setup_quality": "strong",
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.02,
            "sma_20": 98.0,
            "rsi_14": 62.0,
            "macd": 1.2,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.0,
            "close_position_in_range": 0.61,
            "chart_patterns": [],
        },
    }

    annotated = _annotate_technical_context_with_learning(
        {"top_longs": [plain, emerging], "top_shorts": [], "selected_candidates": [plain, emerging]},
        {},
        {},
    )

    assert annotated["top_longs"][0]["symbol"] == "QCOM"
    assert "emerging_leader_momentum" in annotated["top_longs"][0]["rank_priority_reason"]
    assert annotated["top_longs"][0]["rank_priority_components"]["emerging_leader_momentum_component"] > 0


def test_select_deterministic_candidates_allows_more_extended_leader_momentum_with_score_twelve():
    leader = _selection_candidate(
        "MU",
        score=12,
        return_20d=0.45,
        relative_return_20d=0.45,
        rsi_14=76.6,
        volume_zscore_20=-1.8,
        close_position_in_range=0.89,
        close=115.0,
        sma_20=100.0,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    leader["relative_return_20d"] = 0.45

    plain = _selection_candidate(
        "PLAIN",
        score=16,
        return_20d=0.04,
        rsi_14=67.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, leader],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
    )

    promoted = next(item for item in selected if item["symbol"] == "MU")
    assert "leader_momentum_extension" in promoted["selection_reason"]


def test_select_deterministic_candidates_promotes_relaxed_leader_momentum_with_score_eleven():
    leader = _selection_candidate(
        "MU",
        score=11,
        return_20d=0.36,
        rsi_14=70.2,
        volume_zscore_20=-1.9,
        close_position_in_range=0.4,
        close=133.0,
        sma_20=100.0,
        chart_patterns=[{"bias": "bullish", "status": "confirmed"}],
    )
    leader["relative_return_20d"] = 0.26
    plain = _selection_candidate(
        "PLAIN",
        score=15,
        return_20d=0.03,
        rsi_14=64.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, leader],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
    )

    promoted = next(item for item in selected if item["symbol"] == "MU")
    assert "leader_momentum_extension" in promoted["selection_reason"]


def test_select_deterministic_candidates_promotes_emerging_leader_momentum():
    emerging = _selection_candidate(
        "DDOG",
        score=10,
        return_20d=0.11,
        rsi_14=76.0,
        volume_zscore_20=1.5,
        close_position_in_range=0.88,
        close=107.4,
        sma_20=100.0,
        chart_patterns=[],
    )
    plain = _selection_candidate(
        "PLAIN",
        score=14,
        return_20d=0.03,
        rsi_14=64.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, emerging],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
    )

    assert selected[0]["symbol"] == "DDOG"
    assert "emerging_leader_momentum" in selected[0]["selection_reason"]
    assert selected[0]["selection_components"]["emerging_leader_momentum_component"] > 0
    assert selected[0]["selection_components"]["volume_component"] > 0.0


def test_select_deterministic_candidates_does_not_promote_emerging_leader_above_score_range():
    low_score = _selection_candidate(
        "LOW",
        score=9,
        return_20d=0.12,
        rsi_14=82.0,
        volume_zscore_20=-1.8,
        close_position_in_range=0.9,
        close=108.0,
        sma_20=100.0,
        chart_patterns=[],
    )
    plain = _selection_candidate(
        "PLAIN",
        score=14,
        return_20d=0.03,
        rsi_14=64.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, low_score],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
    )

    low = next(item for item in selected if item["symbol"] == "LOW")
    assert "emerging_leader_momentum" not in low["selection_reason"]
    assert low["selection_components"]["emerging_leader_momentum_component"] == 0.0


def test_select_deterministic_candidates_promotes_parabolic_leader_momentum():
    parabolic = _selection_candidate(
        "INTC",
        score=15,
        return_20d=0.98,
        rsi_14=87.4,
        volume_zscore_20=-0.8,
        close=38.5,
        sma_20=28.4,
        chart_patterns=[
            {"bias": "bullish", "status": "confirmed"},
            {"bias": "bullish", "status": "confirmed"},
        ],
    )
    plain = _selection_candidate(
        "PLAIN",
        score=13,
        return_20d=0.05,
        rsi_14=64.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, parabolic],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
        settings=Settings(SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=False),
    )

    assert selected[0]["symbol"] == "INTC"
    assert "parabolic_leader_momentum" in selected[0]["selection_reason"]
    assert selected[0]["selection_components"]["parabolic_leader_momentum_component"] > 0


def test_select_deterministic_candidates_promotes_top_long_alignment():
    aligned = _selection_candidate(
        "CSCO",
        score=15,
        return_20d=0.16,
        rsi_14=69.5,
        volume_zscore_20=-1.8,
        close=107.0,
        sma_20=100.0,
        chart_patterns=[
            {"bias": "bullish", "status": "confirmed"},
            {"bias": "bullish", "status": "confirmed"},
        ],
    )
    aligned["top_long_rank"] = 7
    plain = _selection_candidate(
        "PLAIN",
        score=16,
        return_20d=0.03,
        rsi_14=64.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, aligned],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
    )

    promoted = next(item for item in selected if item["symbol"] == "CSCO")
    assert "top_long_alignment" in promoted["selection_reason"]
    assert promoted["selection_components"]["top_long_alignment_component"] > 0.0


def test_select_deterministic_candidates_promotes_constructive_early_pattern():
    constructive = _selection_candidate(
        "FTNT",
        score=14,
        return_20d=0.074,
        return_60d=0.041,
        rsi_14=67.2,
        volume_zscore_20=-1.9,
        close=106.8,
        sma_20=100.0,
        bollinger_pct_b_20=0.88,
        chart_patterns=[
            {"bias": "bullish", "status": "confirmed"},
            {"bias": "bullish", "status": "confirmed"},
        ],
    )
    plain = _selection_candidate(
        "PLAIN",
        score=15,
        return_20d=0.03,
        rsi_14=64.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, constructive],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
    )

    promoted = next(item for item in selected if item["symbol"] == "FTNT")
    assert "constructive_early_pattern" in promoted["selection_reason"]
    assert promoted["selection_components"]["constructive_early_component"] > 0.0
    assert promoted["selection_components"]["volume_component"] < 0.0


def test_annotate_technical_context_promotes_constructive_early_pattern():
    technical_context = {
        "top_longs": [
            _selection_candidate(
                "FTNT",
                score=14,
                return_20d=0.074,
                return_60d=0.041,
                rsi_14=67.2,
                volume_zscore_20=-1.9,
                close=106.8,
                sma_20=100.0,
                bollinger_pct_b_20=0.88,
                chart_patterns=[
                    {"bias": "bullish", "status": "confirmed"},
                    {"bias": "bullish", "status": "confirmed"},
                ],
            ),
            _selection_candidate(
                "PLAIN",
                score=15,
                return_20d=0.03,
                rsi_14=64.0,
                volume_zscore_20=0.1,
                chart_patterns=[],
            ),
        ]
    }

    annotated = _annotate_technical_context_with_learning(
        technical_context,
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
    )

    promoted = next(item for item in annotated["top_longs"] if item["symbol"] == "FTNT")
    assert "constructive_early_pattern" in promoted["rank_priority_reason"]
    assert promoted["rank_priority_components"]["constructive_early_component"] > 0.0
    assert promoted["rank_priority_components"]["volume_component"] < 0.0


def test_select_deterministic_candidates_blocks_parabolic_leader_below_threshold():
    low = _selection_candidate(
        "LOW",
        score=13,
        return_20d=0.30,
        rsi_14=86.0,
        volume_zscore_20=0.2,
        close=38.5,
        sma_20=28.4,
        chart_patterns=[],
    )
    plain = _selection_candidate(
        "PLAIN",
        score=15,
        return_20d=0.03,
        rsi_14=64.0,
        volume_zscore_20=0.1,
        chart_patterns=[],
    )

    selected, _metadata = _select_deterministic_candidates(
        [plain, low],
        {"setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.0, "win_rate": 0.5, "matured": 20}]},
        {},
        limit=2,
    )

    low_selected = next(item for item in selected if item["symbol"] == "LOW")
    assert "parabolic_leader_momentum" not in low_selected["selection_reason"]
    assert low_selected["selection_components"]["parabolic_leader_momentum_component"] == 0.0


def test_annotate_technical_context_rewards_orderly_breakout():
    orderly = {
        "symbol": "ORDR",
        "direction": "long",
        "score": 15,
        "setup_quality": "strong",
        "relative_return_20d": 0.07,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.09,
            "sma_20": 95.0,
            "rsi_14": 69.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.4,
            "orderly_breakout_long": True,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    }
    baseline = {
        "symbol": "BASE",
        "direction": "long",
        "score": 15,
        "setup_quality": "strong",
        "relative_return_20d": 0.07,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.09,
            "sma_20": 95.0,
            "rsi_14": 69.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.1,
            "chart_patterns": [],
        },
    }

    annotated = _annotate_technical_context_with_learning(
        {"top_longs": [baseline, orderly], "top_shorts": [], "selected_candidates": [baseline, orderly]},
        {},
        {},
    )

    assert annotated["top_longs"][0]["symbol"] == "ORDR"
    assert "orderly_breakout" in annotated["top_longs"][0]["rank_priority_reason"]


def test_annotate_technical_context_keeps_missing_prior_as_null_edge():
    candidate = {
        "symbol": "NEW",
        "direction": "long",
        "score": 18,
        "setup_quality": "strong",
        "relative_return_20d": 0.12,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.16,
            "sma_20": 95.0,
            "rsi_14": 66.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.1,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    }

    annotated = _annotate_technical_context_with_learning(
        {"top_longs": [candidate], "top_shorts": [], "selected_candidates": [candidate]},
        {},
        {},
    )

    row = annotated["top_longs"][0]
    assert row["setup_edge_3d"] is None
    assert row["effective_setup_edge_3d"] is None
    assert row["learning_prior"]["matched_on"] == "none"
    assert "no_recent_edge_history" in row["rank_priority_reason"]


def test_annotate_technical_context_promotes_same_session_intraday_momentum(tmp_path):
    store = Store(tmp_path / "state" / "agente_bolsa.sqlite3", tmp_path / "logs" / "agents")
    store.ensure_schema()
    for idx, price in enumerate([100.0, 104.0, 108.0], start=1):
        store.save_signal_outcome(
            signal_id=f"scan{idx}:HOOD",
            source_run_id=f"scan{idx}",
            source="intraday_scan",
            symbol="HOOD",
            signal_date="2026-05-28",
            decision="candidate",
            features={
                "direction": "long",
                "score": 14,
                "entry_price": price,
                "selected_for_llm": False,
                "rsi_14": 62.0,
                "volume_zscore_20": 0.8,
                "distance_sma20": 0.08,
                "chart_patterns": {"bullish_confirmed_count": 2},
            },
            outcome={},
        )

    repeated = _selection_candidate(
        "HOOD",
        score=14,
        rsi_14=78.0,
        volume_zscore_20=0.8,
        chart_patterns=[],
        event_momentum_long=True,
    )
    repeated["last_date"] = "2026-05-28"
    baseline = _selection_candidate("BASE", score=15, volume_zscore_20=0.1, chart_patterns=[])
    baseline["last_date"] = "2026-05-28"

    annotated = _annotate_technical_context_with_learning(
        {
            "as_of": "2026-05-28T19:51:59+00:00",
            "top_longs": [baseline, repeated],
            "top_shorts": [],
            "all_candidates": [baseline, repeated],
        },
        {},
        {},
        tmp_path,
    )

    row = annotated["selected_candidates"][0]
    assert row["symbol"] == "HOOD"
    assert "same_session_intraday_momentum" in row["selection_reason"]
    assert row["same_session_intraday"]["observations"] == 3
    assert row["same_session_intraday"]["same_session_return"] == 0.08


def test_entry_quality_gate_blocks_negative_recent_prior(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    candidate = _quality_context(
        technical_state={
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 95.0,
            "rsi_14": 72.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.5,
            "chart_patterns": [],
        }
    )["top_longs"][0]
    features = _candidate_learning_features(candidate)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": -0.01, "win_rate": 0.35, "matured": 10}],
                "setup_priors_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "expected_edge": -0.03,
                        "win_rate": 0.3,
                        "matured": 8,
                        "confidence_weight": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved, reason, checks = validate_entry_quality(
        settings,
        _quality_recommendation(),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is False
    assert "prior reciente desfavorable" in reason
    assert checks["learning_prior"]["expected_edge_3d"] == -0.03


def test_entry_quality_gate_blocks_weak_rsi_with_weak_volume(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    candidate = _quality_context(
        technical_state={
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 96.0,
            "rsi_14": 58.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": -0.4,
            "chart_patterns": [],
        }
    )["top_longs"][0]

    approved, reason, checks = validate_entry_quality(
        settings,
        _quality_recommendation(),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is False
    assert "RSI flojo con volumen relativo debil" in reason
    assert checks["rsi_14"] == 58.0
    assert checks["volume_zscore_20"] == -0.4


def test_entry_quality_gate_blocks_high_prior_estimation_error(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    candidate = _quality_context(
        technical_state={
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 96.0,
            "rsi_14": 67.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.3,
            "chart_patterns": [],
        }
    )["top_longs"][0]
    features = _candidate_learning_features(candidate)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.01, "win_rate": 0.45, "matured": 10}],
                "setup_priors_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "expected_edge": 0.015,
                        "win_rate": 0.45,
                        "matured": 8,
                        "confidence_weight": 1.0,
                    }
                ],
                "prior_accuracy_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "matured": 7,
                        "expected_edge": 0.015,
                        "realized_avg_return": -0.01,
                        "avg_error": 0.025,
                        "avg_abs_error": 0.05,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved, reason, checks = validate_entry_quality(
        settings,
        _quality_recommendation(),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is False
    assert "sobreestima el edge" in reason
    assert checks["prior_accuracy"]["avg_abs_error"] == 0.05


def test_entry_quality_gate_keeps_strong_prior_even_with_error_signal(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    candidate = _quality_context(
        technical_state={
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 96.0,
            "rsi_14": 67.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.3,
            "chart_patterns": [],
        }
    )["top_longs"][0]
    features = _candidate_learning_features(candidate)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [{"setup": "baseline_trend", "avg_return": 0.03, "win_rate": 0.6, "matured": 10}],
                "setup_priors_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "expected_edge": 0.03,
                        "win_rate": 0.6,
                        "matured": 8,
                        "confidence_weight": 1.0,
                    }
                ],
                "prior_accuracy_3d": [
                    {
                        "profile_key": _prior_profile_key(features),
                        "setup": "baseline_trend",
                        "matured": 7,
                        "expected_edge": 0.03,
                        "realized_avg_return": 0.0,
                        "avg_error": 0.03,
                        "avg_abs_error": 0.05,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved, reason, checks = validate_entry_quality(
        settings,
        _quality_recommendation(),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["learning_prior"]["expected_edge_3d"] == 0.03


def test_sizing_adjustment_for_recommendation_reflects_prior_and_calibration():
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.92,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        target_exposure_pct=0.05,
    )
    candidate = _quality_context()["top_longs"][0]
    candidate["learning_prior"] = {
        "expected_edge_3d": 0.04,
        "sample_size_3d": 8,
        "confidence_weight_3d": 1.0,
    }
    technical_context = {"top_longs": [candidate], "top_shorts": []}
    digest = {
        "confidence_calibration_3d": [
            {"bucket": "gte0_90", "avg_return": 0.03, "win_rate": 0.6, "matured": 9}
        ]
    }

    adjustment = _sizing_adjustment_for_recommendation(
        recommendation,
        technical_context,
        digest,
        {},
    )

    assert adjustment["size_multiplier"] == 1.15
    assert "strong_recent_prior" in adjustment["reason"]
    assert "strong_confidence_calibration" in adjustment["reason"]


def test_sizing_adjustment_penalizes_high_prior_estimation_error():
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.92,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        target_exposure_pct=0.05,
    )
    candidate = _quality_context()["top_longs"][0]
    candidate["learning_prior"] = {
        "profile_key": "baseline_trend|score:12_14",
        "expected_edge_3d": 0.04,
        "sample_size_3d": 8,
        "confidence_weight_3d": 1.0,
    }
    technical_context = {"top_longs": [candidate], "top_shorts": []}
    digest = {
        "confidence_calibration_3d": [
            {"bucket": "gte0_90", "avg_return": 0.03, "win_rate": 0.6, "matured": 9}
        ],
        "prior_accuracy_3d": [
            {"profile_key": "baseline_trend|score:12_14", "avg_abs_error": 0.05, "matured": 7}
        ],
    }

    adjustment = _sizing_adjustment_for_recommendation(
        recommendation,
        technical_context,
        digest,
        {},
    )

    assert adjustment["size_multiplier"] == 0.924
    assert "high_prior_estimation_error" in adjustment["reason"]
