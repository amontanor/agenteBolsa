"""Runtime configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default="local-llama", alias="OPENAI_API_KEY")
    openai_api_base: str = Field(
        default="http://127.0.0.1:8080/v1",
        validation_alias=AliasChoices("OPENAI_API_BASE", "OPENAI_BASE_URL", "LLM_BASE_URL"),
    )
    openai_model: str = Field(
        default="qwen3.6-27b",
        validation_alias=AliasChoices("OPENAI_MODEL_NAME", "OPENAI_MODEL", "LLM_MODEL"),
    )
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_max_tokens: int | None = Field(default=1200, alias="LLM_MAX_TOKENS")
    llm_timeout_seconds: int = Field(default=120, alias="LLM_TIMEOUT_SECONDS")
    crewai_planning: bool = Field(default=False, alias="CREWAI_PLANNING")
    crew_agent_max_iter: int = Field(default=1, alias="CREW_AGENT_MAX_ITER")
    crew_agent_max_execution_seconds: int = Field(default=120, alias="CREW_AGENT_MAX_EXECUTION_SECONDS")

    trading_mode: Literal["paper", "live"] = Field(default="paper", alias="TRADING_MODE")
    allow_live_trading: bool = Field(default=False, alias="ALLOW_LIVE_TRADING")
    broker: str = Field(default="alpaca", alias="BROKER")
    alpaca_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ALPACA_API_KEY", "ALPACA_KEY", "APCA_API_KEY_ID"),
    )
    alpaca_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY"),
    )
    alpaca_endpoint: str | None = Field(
        default="https://paper-api.alpaca.markets",
        validation_alias=AliasChoices(
            "ALPACA_PAPER_ENDPOINT",
            "ALPACA_ENDPOINT",
            "ALPACA_API_BASE",
            "APCA_API_BASE_URL",
        ),
    )
    alpaca_paper: bool = Field(default=True, alias="ALPACA_PAPER")

    default_universe: str = Field(
        default="SPY,QQQ,AAPL,MSFT,NVDA,AMZN,META,GOOGL,TSLA",
        alias="DEFAULT_UNIVERSE",
    )
    benchmark_symbol: str = Field(default="SPY", alias="BENCHMARK_SYMBOL")
    market_data_provider: str = Field(default="auto", alias="MARKET_DATA_PROVIDER")

    max_portfolio_exposure: float = Field(default=0.50, alias="MAX_PORTFOLIO_EXPOSURE")
    max_position_exposure: float = Field(default=0.05, alias="MAX_POSITION_EXPOSURE")
    max_daily_loss: float = Field(default=0.02, alias="MAX_DAILY_LOSS")
    max_drawdown: float = Field(default=0.10, alias="MAX_DRAWDOWN")
    min_backtest_trades: int = Field(default=50, alias="MIN_BACKTEST_TRADES")
    min_out_of_sample_sharpe: float = Field(default=0.80, alias="MIN_OUT_OF_SAMPLE_SHARPE")
    max_strategy_drawdown: float = Field(default=0.15, alias="MAX_STRATEGY_DRAWDOWN")
    backtest_gate_enabled: bool = Field(default=True, alias="BACKTEST_GATE_ENABLED")
    backtest_gate_lookback_days: int = Field(default=730, alias="BACKTEST_GATE_LOOKBACK_DAYS")
    backtest_gate_min_trades: int = Field(default=10, alias="BACKTEST_GATE_MIN_TRADES")
    backtest_gate_min_hit_rate: float = Field(default=0.45, alias="BACKTEST_GATE_MIN_HIT_RATE")
    backtest_gate_min_profit_factor: float = Field(default=1.05, alias="BACKTEST_GATE_MIN_PROFIT_FACTOR")
    backtest_gate_max_drawdown: float = Field(default=0.10, alias="BACKTEST_GATE_MAX_DRAWDOWN")
    backtest_gate_min_alpha_vs_benchmark: float = Field(default=0.0, alias="BACKTEST_GATE_MIN_ALPHA_VS_BENCHMARK")
    backtest_gate_min_trade_window_alpha: float = Field(default=0.0, alias="BACKTEST_GATE_MIN_TRADE_WINDOW_ALPHA")
    backtest_gate_min_regime_trades: int = Field(default=2, alias="BACKTEST_GATE_MIN_REGIME_TRADES")
    backtest_gate_max_negative_regimes: int = Field(default=1, alias="BACKTEST_GATE_MAX_NEGATIVE_REGIMES")
    entry_quality_gate_enabled: bool = Field(default=True, alias="ENTRY_QUALITY_GATE_ENABLED")
    entry_quality_min_score: int = Field(default=12, alias="ENTRY_QUALITY_MIN_SCORE")
    entry_quality_max_rsi: float = Field(default=85.0, alias="ENTRY_QUALITY_MAX_RSI")
    entry_quality_extreme_rsi_min_score: int = Field(default=15, alias="ENTRY_QUALITY_EXTREME_RSI_MIN_SCORE")
    entry_quality_max_sma20_distance: float = Field(default=0.12, alias="ENTRY_QUALITY_MAX_SMA20_DISTANCE")
    entry_quality_extended_sma20_distance: float = Field(
        default=0.08,
        alias="ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE",
    )
    entry_quality_extended_min_relative_return: float = Field(
        default=0.02,
        alias="ENTRY_QUALITY_EXTENDED_MIN_RELATIVE_RETURN",
    )
    entry_quality_extended_min_volume_z: float = Field(
        default=0.0,
        alias="ENTRY_QUALITY_EXTENDED_MIN_VOLUME_Z",
    )
    entry_quality_confirmed_pattern_rsi: float = Field(default=80.0, alias="ENTRY_QUALITY_CONFIRMED_PATTERN_RSI")
    entry_quality_weak_rsi_max: float = Field(default=62.0, alias="ENTRY_QUALITY_WEAK_RSI_MAX")
    entry_quality_weak_volume_max: float = Field(default=0.0, alias="ENTRY_QUALITY_WEAK_VOLUME_MAX")
    entry_quality_prior_error_min_samples: int = Field(default=5, alias="ENTRY_QUALITY_PRIOR_ERROR_MIN_SAMPLES")
    entry_quality_max_prior_avg_abs_error: float = Field(default=0.04, alias="ENTRY_QUALITY_MAX_PRIOR_AVG_ABS_ERROR")
    entry_quality_range_expansion_max_sma20_distance: float = Field(
        default=0.22,
        alias="ENTRY_QUALITY_RANGE_EXPANSION_MAX_SMA20_DISTANCE",
    )
    entry_quality_range_expansion_max_rsi: float = Field(
        default=78.0,
        alias="ENTRY_QUALITY_RANGE_EXPANSION_MAX_RSI",
    )
    entry_quality_orderly_breakout_max_sma20_distance: float = Field(
        default=0.22,
        alias="ENTRY_QUALITY_ORDERLY_BREAKOUT_MAX_SMA20_DISTANCE",
    )
    entry_quality_orderly_breakout_max_rsi: float = Field(
        default=74.0,
        alias="ENTRY_QUALITY_ORDERLY_BREAKOUT_MAX_RSI",
    )
    entry_quality_orderly_breakout_min_score: int = Field(
        default=14,
        alias="ENTRY_QUALITY_ORDERLY_BREAKOUT_MIN_SCORE",
    )
    entry_quality_orderly_breakout_min_volume_z: float = Field(
        default=0.25,
        alias="ENTRY_QUALITY_ORDERLY_BREAKOUT_MIN_VOLUME_Z",
    )
    entry_quality_momentum_confirmation_max_sma20_distance: float = Field(
        default=0.22,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MAX_SMA20_DISTANCE",
    )
    entry_quality_momentum_confirmation_max_rsi: float = Field(
        default=84.0,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MAX_RSI",
    )
    entry_quality_momentum_confirmation_min_score: int = Field(
        default=15,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MIN_SCORE",
    )
    entry_quality_momentum_confirmation_min_volume_z: float = Field(
        default=0.75,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MIN_VOLUME_Z",
    )
    entry_quality_momentum_confirmation_min_return_20d: float = Field(
        default=0.18,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MIN_RETURN_20D",
    )
    auto_paper_trading: bool = Field(default=False, alias="AUTO_PAPER_TRADING")
    require_human_approval: bool = Field(default=True, alias="REQUIRE_HUMAN_APPROVAL")
    deterministic_trade_fallback_enabled: bool = Field(
        default=True,
        alias="DETERMINISTIC_TRADE_FALLBACK_ENABLED",
    )
    max_risk_per_trade: float = Field(default=0.01, alias="MAX_RISK_PER_TRADE")
    max_total_open_risk: float = Field(default=0.03, alias="MAX_TOTAL_OPEN_RISK")
    max_orders_per_cycle: int = Field(default=3, alias="MAX_ORDERS_PER_CYCLE")
    max_daily_buy_orders: int = Field(default=3, alias="MAX_DAILY_BUY_ORDERS")
    min_order_notional: float = Field(default=100.0, alias="MIN_ORDER_NOTIONAL")
    allow_position_adds: bool = Field(default=False, alias="ALLOW_POSITION_ADDS")
    min_llm_confidence_to_trade: float = Field(default=0.65, alias="MIN_LLM_CONFIDENCE_TO_TRADE")
    allow_short_selling: bool = Field(default=False, alias="ALLOW_SHORT_SELLING")
    use_bracket_orders: bool = Field(default=True, alias="USE_BRACKET_ORDERS")
    operational_kill_switch_enabled: bool = Field(default=True, alias="OPERATIONAL_KILL_SWITCH_ENABLED")
    shadow_rule_walk_forward_window_sessions: int = Field(default=5, alias="SHADOW_RULE_WF_WINDOW_SESSIONS")
    shadow_rule_walk_forward_min_cases_per_window: int = Field(default=3, alias="SHADOW_RULE_WF_MIN_CASES_PER_WINDOW")
    shadow_rule_walk_forward_min_windows: int = Field(default=3, alias="SHADOW_RULE_WF_MIN_WINDOWS")
    shadow_rule_walk_forward_min_stable_ratio: float = Field(
        default=0.67,
        alias="SHADOW_RULE_WF_MIN_STABLE_RATIO",
    )
    llm_exit_exception_min_confidence: float = Field(
        default=0.95,
        alias="LLM_EXIT_EXCEPTION_MIN_CONFIDENCE",
    )
    llm_exit_exception_min_drawdown: float = Field(
        default=0.08,
        alias="LLM_EXIT_EXCEPTION_MIN_DRAWDOWN",
    )

    continuous_improvement_enabled: bool = Field(default=True, alias="CONTINUOUS_IMPROVEMENT_ENABLED")
    improvement_llm_enabled: bool = Field(default=False, alias="IMPROVEMENT_LLM_ENABLED")
    improvement_llm_provider: str = Field(default="mimo", alias="IMPROVEMENT_LLM_PROVIDER")
    improvement_llm_base_url: str = Field(
        default="https://api.xiaomimimo.com/v1",
        alias="IMPROVEMENT_LLM_BASE_URL",
    )
    improvement_llm_api_key: str | None = Field(default=None, alias="IMPROVEMENT_LLM_API_KEY")
    improvement_llm_model: str = Field(default="mimo-v2.5", alias="IMPROVEMENT_LLM_MODEL")
    improvement_llm_orchestrator_model: str = Field(
        default="mimo-v2.5-pro",
        alias="IMPROVEMENT_LLM_ORCHESTRATOR_MODEL",
    )
    improvement_llm_temperature: float = Field(default=0.2, alias="IMPROVEMENT_LLM_TEMPERATURE")
    improvement_llm_max_tokens: int = Field(default=6000, alias="IMPROVEMENT_LLM_MAX_TOKENS")
    improvement_llm_timeout_seconds: int = Field(default=120, alias="IMPROVEMENT_LLM_TIMEOUT_SECONDS")
    improvement_llm_retries: int = Field(default=2, alias="IMPROVEMENT_LLM_RETRIES")
    improvement_dry_run: bool = Field(default=True, alias="IMPROVEMENT_DRY_RUN")
    allow_auto_apply_improvements: bool = Field(default=False, alias="ALLOW_AUTO_APPLY_IMPROVEMENTS")
    require_human_approval_for_code_changes: bool = Field(
        default=True,
        alias="REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES",
    )
    require_human_approval_for_high_risk: bool = Field(
        default=True,
        alias="REQUIRE_HUMAN_APPROVAL_FOR_HIGH_RISK",
    )
    continuous_improvement_schedule_enabled: bool = Field(
        default=False,
        alias="CONTINUOUS_IMPROVEMENT_SCHEDULE_ENABLED",
    )
    continuous_improvement_time_local: str = Field(
        default="23:30",
        alias="CONTINUOUS_IMPROVEMENT_TIME_LOCAL",
    )
    continuous_improvement_runtime_interval_seconds: int = Field(
        default=60,
        alias="CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS",
    )
    continuous_improvement_event_cooldown_seconds: int = Field(
        default=1800,
        alias="CONTINUOUS_IMPROVEMENT_EVENT_COOLDOWN_SECONDS",
    )
    continuous_improvement_runtime_loop_sleep_seconds: int = Field(
        default=15,
        alias="CONTINUOUS_IMPROVEMENT_RUNTIME_LOOP_SLEEP_SECONDS",
    )
    continuous_improvement_max_proposals_per_cycle: int = Field(
        default=5,
        alias="CONTINUOUS_IMPROVEMENT_MAX_PROPOSALS_PER_CYCLE",
    )
    continuous_improvement_workspace_dir: Path | None = Field(
        default=None,
        alias="CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR",
    )

    run_interval_seconds: int = Field(default=900, alias="RUN_INTERVAL_SECONDS")
    portfolio_watch_interval_seconds: int = Field(
        default=60,
        alias="PORTFOLIO_WATCH_INTERVAL_SECONDS",
    )
    market_cycle_interval_minutes: int = Field(
        default=15,
        alias="MARKET_CYCLE_INTERVAL_MINUTES",
    )
    closed_market_study_interval_minutes: int = Field(
        default=15,
        alias="CLOSED_MARKET_STUDY_INTERVAL_MINUTES",
    )
    closed_market_study_universe: str = Field(
        default="sp500",
        alias="CLOSED_MARKET_STUDY_UNIVERSE",
    )
    closed_market_study_max_symbols: int = Field(default=500, alias="CLOSED_MARKET_STUDY_MAX_SYMBOLS")
    intraday_technical_scan_enabled: bool = Field(default=True, alias="INTRADAY_TECHNICAL_SCAN_ENABLED")
    intraday_technical_scan_universe: str = Field(default="sp500_plus_intraday_focus", alias="INTRADAY_TECHNICAL_SCAN_UNIVERSE")
    intraday_technical_scan_max_symbols: int = Field(default=0, alias="INTRADAY_TECHNICAL_SCAN_MAX_SYMBOLS")
    intraday_same_session_momentum_enabled: bool = Field(
        default=True,
        alias="INTRADAY_SAME_SESSION_MOMENTUM_ENABLED",
    )
    intraday_same_session_min_observations: int = Field(
        default=3,
        alias="INTRADAY_SAME_SESSION_MIN_OBSERVATIONS",
    )
    intraday_same_session_min_score: int = Field(
        default=14,
        alias="INTRADAY_SAME_SESSION_MIN_SCORE",
    )
    intraday_same_session_min_return: float = Field(
        default=0.04,
        alias="INTRADAY_SAME_SESSION_MIN_RETURN",
    )
    intraday_same_session_min_volume_z: float = Field(
        default=0.50,
        alias="INTRADAY_SAME_SESSION_MIN_VOLUME_Z",
    )
    intraday_same_session_min_bullish_patterns: int = Field(
        default=2,
        alias="INTRADAY_SAME_SESSION_MIN_BULLISH_PATTERNS",
    )
    intraday_same_session_max_sma20_distance: float = Field(
        default=0.30,
        alias="INTRADAY_SAME_SESSION_MAX_SMA20_DISTANCE",
    )
    intraday_same_session_max_rsi: float = Field(
        default=84.0,
        alias="INTRADAY_SAME_SESSION_MAX_RSI",
    )
    intraday_same_session_selection_bonus: float = Field(
        default=0.03,
        alias="INTRADAY_SAME_SESSION_SELECTION_BONUS",
    )
    intraday_same_session_priority_bonus: float = Field(
        default=0.025,
        alias="INTRADAY_SAME_SESSION_PRIORITY_BONUS",
    )
    intraday_same_session_leader_min_observations: int = Field(
        default=5,
        alias="INTRADAY_SAME_SESSION_LEADER_MIN_OBSERVATIONS",
    )
    intraday_same_session_leader_min_score: int = Field(
        default=11,
        alias="INTRADAY_SAME_SESSION_LEADER_MIN_SCORE",
    )
    intraday_same_session_leader_min_return: float = Field(
        default=0.05,
        alias="INTRADAY_SAME_SESSION_LEADER_MIN_RETURN",
    )
    intraday_same_session_leader_min_bullish_patterns: int = Field(
        default=2,
        alias="INTRADAY_SAME_SESSION_LEADER_MIN_BULLISH_PATTERNS",
    )
    intraday_same_session_leader_max_sma20_distance: float = Field(
        default=0.22,
        alias="INTRADAY_SAME_SESSION_LEADER_MAX_SMA20_DISTANCE",
    )
    intraday_same_session_leader_max_rsi: float = Field(
        default=82.0,
        alias="INTRADAY_SAME_SESSION_LEADER_MAX_RSI",
    )
    intraday_same_session_leader_selection_bonus: float = Field(
        default=0.028,
        alias="INTRADAY_SAME_SESSION_LEADER_SELECTION_BONUS",
    )
    intraday_same_session_leader_priority_bonus: float = Field(
        default=0.022,
        alias="INTRADAY_SAME_SESSION_LEADER_PRIORITY_BONUS",
    )
    breakout_extra_symbols: str = Field(default="", alias="BREAKOUT_EXTRA_SYMBOLS")
    intraday_news_sentiment_enabled: bool = Field(default=False, alias="INTRADAY_NEWS_SENTIMENT_ENABLED")
    news_sentiment_enabled: bool = Field(default=True, alias="NEWS_SENTIMENT_ENABLED")
    news_sentiment_top_n: int = Field(default=10, alias="NEWS_SENTIMENT_TOP_N")
    trade_selection_top_n: int = Field(default=16, alias="TRADE_SELECTION_TOP_N")
    news_items_per_symbol: int = Field(default=5, alias="NEWS_ITEMS_PER_SYMBOL")
    news_sentiment_fail_closed_for_buys: bool = Field(
        default=True,
        alias="NEWS_SENTIMENT_FAIL_CLOSED_FOR_BUYS",
    )
    open_position_news_guard_enabled: bool = Field(default=True, alias="OPEN_POSITION_NEWS_GUARD_ENABLED")
    open_position_news_guard_interval_minutes: int = Field(
        default=30,
        alias="OPEN_POSITION_NEWS_GUARD_INTERVAL_MINUTES",
    )
    pre_earnings_enabled: bool = Field(default=True, alias="PRE_EARNINGS_ENABLED")
    pre_earnings_days: int = Field(default=5, alias="PRE_EARNINGS_DAYS")
    pre_earnings_before_close_minutes: int = Field(default=60, alias="PRE_EARNINGS_BEFORE_CLOSE_MINUTES")
    pre_earnings_time_market: str = Field(default="15:00", alias="PRE_EARNINGS_TIME_MARKET")
    pre_earnings_universe: str = Field(default="", alias="PRE_EARNINGS_UNIVERSE")
    pre_earnings_max_symbols: int = Field(default=0, alias="PRE_EARNINGS_MAX_SYMBOLS")
    pre_earnings_trade_enabled: bool = Field(default=False, alias="PRE_EARNINGS_TRADE_ENABLED")
    pre_earnings_trade_min_score_v2: float = Field(default=70.0, alias="PRE_EARNINGS_TRADE_MIN_SCORE_V2")
    pre_earnings_trade_target_exposure_pct: float = Field(
        default=0.025,
        alias="PRE_EARNINGS_TRADE_TARGET_EXPOSURE_PCT",
    )
    fmp_api_key: str | None = Field(default=None, alias="FMP_API_KEY")
    daily_study_time_local: str = Field(default="23:00", alias="DAILY_STUDY_TIME_LOCAL")
    opportunity_snapshot_times_local: str = Field(
        default="16:00,19:00,21:00",
        alias="OPPORTUNITY_SNAPSHOT_TIMES_LOCAL",
    )
    post_market_review_enabled: bool = Field(default=True, alias="POST_MARKET_REVIEW_ENABLED")
    post_market_review_use_llm: bool = Field(default=True, alias="POST_MARKET_REVIEW_USE_LLM")
    local_timezone: str = Field(default="Europe/Madrid", alias="LOCAL_TIMEZONE")
    market_calendar: str = Field(default="XNYS", alias="MARKET_CALENDAR")
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    retention_enabled: bool = Field(default=True, alias="RETENTION_ENABLED")
    report_retention_days: int = Field(default=30, alias="REPORT_RETENTION_DAYS")
    log_retention_days: int = Field(default=30, alias="LOG_RETENTION_DAYS")
    cache_retention_days: int = Field(default=7, alias="CACHE_RETENTION_DAYS")
    disabled_report_prefixes: str = Field(
        default=(
            "postmortem_signals,missed_opportunities,decision_compare,"
            "walk_forward_validation,session_retrospective"
        ),
        alias="DISABLED_REPORT_PREFIXES",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def universe(self) -> list[str]:
        return [symbol.strip().upper() for symbol in self.default_universe.split(",") if symbol.strip()]

    @property
    def breakout_watchlist(self) -> list[str]:
        return [symbol.strip().upper() for symbol in self.breakout_extra_symbols.split(",") if symbol.strip()]

    @property
    def opportunity_snapshot_times(self) -> list[str]:
        from .tools.opportunities import parse_opportunity_snapshot_times

        return parse_opportunity_snapshot_times(self.opportunity_snapshot_times_local)

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def agent_logs_dir(self) -> Path:
        return self.logs_dir / "agents"

    @property
    def checkpoints_dir(self) -> Path:
        return self.data_dir / "checkpoints"

    @property
    def database_path(self) -> Path:
        return self.state_dir / "agente_bolsa.sqlite3"

    @property
    def adaptive_config_path(self) -> Path:
        return self.state_dir / "adaptive_config.json"

    @property
    def improvement_workspace_dir(self) -> Path:
        return (self.continuous_improvement_workspace_dir or self.data_dir.parent).resolve()

    @property
    def disabled_report_prefix_list(self) -> list[str]:
        return [
            item.strip()
            for item in self.disabled_report_prefixes.split(",")
            if item.strip()
        ]

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.state_dir,
            self.logs_dir,
            self.agent_logs_dir,
            self.checkpoints_dir,
            self.data_dir / "cache",
            self.data_dir / "hypotheses",
            self.data_dir / "backtests",
            self.data_dir / "reports",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def assert_trading_safety(self) -> None:
        if self.trading_mode == "paper" and not self.alpaca_paper:
            raise RuntimeError("Configuracion inconsistente: paper trading con ALPACA_PAPER=false.")
        if self.trading_mode == "live" and not self.allow_live_trading:
            raise RuntimeError("Live trading bloqueado: ALLOW_LIVE_TRADING debe ser true.")
        if self.trading_mode == "live" and self.alpaca_paper:
            raise RuntimeError("Configuracion inconsistente: live trading con ALPACA_PAPER=true.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    try:
        from .tools.adaptive_tuning import active_adaptive_overrides

        overrides = active_adaptive_overrides(settings)
        if overrides:
            settings = settings.model_copy(update=overrides)
            settings.ensure_runtime_dirs()
    except Exception:
        pass
    return settings
