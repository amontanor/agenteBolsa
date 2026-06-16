"""Runtime configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_api_base: str = Field(
        default="https://token-plan-ams.xiaomimimo.com/v1",
        validation_alias=AliasChoices("OPENAI_API_BASE", "OPENAI_BASE_URL", "LLM_BASE_URL"),
    )
    openai_model: str = Field(
        default="mimo-v2.5-pro",
        validation_alias=AliasChoices("OPENAI_MODEL_NAME", "OPENAI_MODEL", "LLM_MODEL"),
    )
    llm_primary_preflight_enabled: bool = Field(default=True, alias="LLM_PRIMARY_PREFLIGHT_ENABLED")
    llm_local_fallback_enabled: bool = Field(default=True, alias="LLM_LOCAL_FALLBACK_ENABLED")
    llm_local_fallback_api_key: str | None = Field(default="local-llama", alias="LLM_LOCAL_FALLBACK_API_KEY")
    llm_local_fallback_api_base: str = Field(
        default="http://127.0.0.1:8080/v1",
        alias="LLM_LOCAL_FALLBACK_API_BASE",
    )
    llm_local_fallback_model: str = Field(default="qwen3.6-27b", alias="LLM_LOCAL_FALLBACK_MODEL")
    llm_local_fallback_preflight_enabled: bool = Field(
        default=True,
        alias="LLM_LOCAL_FALLBACK_PREFLIGHT_ENABLED",
    )
    secondary_review_llm_enabled: bool = Field(default=False, alias="SECONDARY_REVIEW_LLM_ENABLED")
    secondary_review_llm_model: str = Field(default="", alias="SECONDARY_REVIEW_LLM_MODEL")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_max_tokens: int | None = Field(default=1200, alias="LLM_MAX_TOKENS")
    llm_timeout_seconds: int = Field(default=120, alias="LLM_TIMEOUT_SECONDS")

    # Router LLM por roles (T0.4). Cada rol cae a la cadena por defecto si no se
    # define modelo/base/key, asi que dejarlos vacios mantiene el comportamiento.
    llm_role_fast_model: str | None = Field(default=None, alias="LLM_ROLE_FAST_MODEL")
    llm_role_fast_base_url: str | None = Field(default=None, alias="LLM_ROLE_FAST_BASE_URL")
    llm_role_fast_api_key: str | None = Field(default=None, alias="LLM_ROLE_FAST_API_KEY")
    llm_role_fast_max_tokens: int | None = Field(default=None, alias="LLM_ROLE_FAST_MAX_TOKENS")
    llm_role_decision_model: str | None = Field(default=None, alias="LLM_ROLE_DECISION_MODEL")
    llm_role_decision_base_url: str | None = Field(default=None, alias="LLM_ROLE_DECISION_BASE_URL")
    llm_role_decision_api_key: str | None = Field(default=None, alias="LLM_ROLE_DECISION_API_KEY")
    llm_role_decision_max_tokens: int | None = Field(default=None, alias="LLM_ROLE_DECISION_MAX_TOKENS")
    llm_role_deep_model: str | None = Field(default=None, alias="LLM_ROLE_DEEP_MODEL")
    llm_role_deep_base_url: str | None = Field(default=None, alias="LLM_ROLE_DEEP_BASE_URL")
    llm_role_deep_api_key: str | None = Field(default=None, alias="LLM_ROLE_DEEP_API_KEY")
    llm_role_deep_max_tokens: int | None = Field(default=None, alias="LLM_ROLE_DEEP_MAX_TOKENS")
    # Presupuesto economico del laboratorio (T5.9). 0 = sin limite.
    llm_daily_budget_usd: float = Field(default=5.0, alias="LLM_DAILY_BUDGET_USD")
    llm_role_deep_daily_budget_usd: float = Field(default=3.0, alias="LLM_ROLE_DEEP_DAILY_BUDGET_USD")
    crewai_planning: bool = Field(default=False, alias="CREWAI_PLANNING")
    crew_agent_max_iter: int = Field(default=1, alias="CREW_AGENT_MAX_ITER")
    crew_agent_max_execution_seconds: int = Field(default=120, alias="CREW_AGENT_MAX_EXECUTION_SECONDS")

    trading_mode: Literal["paper", "live"] = Field(default="paper", alias="TRADING_MODE")
    trade_aggressiveness_profile: Literal["conservative", "opportunistic", "aggressive"] = Field(
        default="opportunistic",
        alias="TRADE_AGGRESSIVENESS_PROFILE",
    )
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
    live_requires_formal_market_data: bool = Field(default=True, alias="LIVE_REQUIRES_FORMAL_MARKET_DATA")
    market_regime_policy_enabled: bool = Field(default=True, alias="MARKET_REGIME_POLICY_ENABLED")

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
        default=0.26,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MAX_SMA20_DISTANCE",
    )
    entry_quality_momentum_confirmation_max_rsi: float = Field(
        default=88.0,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MAX_RSI",
    )
    entry_quality_momentum_confirmation_min_score: int = Field(
        default=15,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MIN_SCORE",
    )
    entry_quality_momentum_confirmation_min_volume_z: float = Field(
        default=0.50,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MIN_VOLUME_Z",
    )
    entry_quality_momentum_confirmation_min_return_20d: float = Field(
        default=0.18,
        alias="ENTRY_QUALITY_MOMENTUM_CONFIRMATION_MIN_RETURN_20D",
    )
    entry_quality_breakout_continuation_max_sma20_distance: float = Field(
        default=0.27,
        alias="ENTRY_QUALITY_BREAKOUT_CONTINUATION_MAX_SMA20_DISTANCE",
    )
    entry_quality_breakout_continuation_max_rsi: float = Field(
        default=84.0,
        alias="ENTRY_QUALITY_BREAKOUT_CONTINUATION_MAX_RSI",
    )
    entry_quality_breakout_continuation_min_score: int = Field(
        default=16,
        alias="ENTRY_QUALITY_BREAKOUT_CONTINUATION_MIN_SCORE",
    )
    entry_quality_breakout_continuation_min_volume_z: float = Field(
        default=1.5,
        alias="ENTRY_QUALITY_BREAKOUT_CONTINUATION_MIN_VOLUME_Z",
    )
    entry_quality_breakout_continuation_min_relative_return_20d: float = Field(
        default=0.12,
        alias="ENTRY_QUALITY_BREAKOUT_CONTINUATION_MIN_RELATIVE_RETURN_20D",
    )
    entry_quality_fallback_constructive_extension_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_ENABLED",
    )
    entry_quality_fallback_constructive_extension_max_selection_rank: int = Field(
        default=3,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_MAX_SELECTION_RANK",
    )
    entry_quality_fallback_constructive_extension_min_score: int = Field(
        default=13,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_MIN_SCORE",
    )
    entry_quality_fallback_constructive_extension_min_return_20d: float = Field(
        default=0.20,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_MIN_RETURN_20D",
    )
    entry_quality_fallback_constructive_extension_min_rsi: float = Field(
        default=72.0,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_MIN_RSI",
    )
    entry_quality_fallback_constructive_extension_max_sma20_distance: float = Field(
        default=0.13,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_MAX_SMA20_DISTANCE",
    )
    entry_quality_fallback_constructive_extension_min_volume_z: float = Field(
        default=0.5,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_MIN_VOLUME_Z",
    )
    entry_quality_fallback_constructive_extension_min_bullish_patterns: int = Field(
        default=1,
        alias="ENTRY_QUALITY_FALLBACK_CONSTRUCTIVE_EXTENSION_MIN_BULLISH_PATTERNS",
    )
    entry_quality_fallback_momentum_extension_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_ENABLED",
    )
    entry_quality_fallback_momentum_extension_max_selection_rank: int = Field(
        default=5,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MAX_SELECTION_RANK",
    )
    entry_quality_fallback_momentum_extension_min_score: int = Field(
        default=16,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MIN_SCORE",
    )
    entry_quality_fallback_momentum_extension_min_return_20d: float = Field(
        default=0.30,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MIN_RETURN_20D",
    )
    entry_quality_fallback_momentum_extension_min_rsi: float = Field(
        default=80.0,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MIN_RSI",
    )
    entry_quality_fallback_momentum_extension_max_rsi: float = Field(
        default=85.0,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MAX_RSI",
    )
    entry_quality_fallback_momentum_extension_max_sma20_distance: float = Field(
        default=0.30,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MAX_SMA20_DISTANCE",
    )
    entry_quality_fallback_momentum_extension_min_volume_z: float = Field(
        default=0.0,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MIN_VOLUME_Z",
    )
    entry_quality_fallback_momentum_extension_min_bullish_patterns: int = Field(
        default=1,
        alias="ENTRY_QUALITY_FALLBACK_MOMENTUM_EXTENSION_MIN_BULLISH_PATTERNS",
    )
    entry_quality_fallback_weak_volume_momentum_extension_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_ENABLED",
    )
    entry_quality_fallback_weak_volume_momentum_extension_max_selection_rank: int = Field(
        default=12,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MAX_SELECTION_RANK",
    )
    entry_quality_fallback_weak_volume_momentum_extension_min_score: int = Field(
        default=15,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MIN_SCORE",
    )
    entry_quality_fallback_weak_volume_momentum_extension_min_return_20d: float = Field(
        default=0.30,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MIN_RETURN_20D",
    )
    entry_quality_fallback_weak_volume_momentum_extension_min_rsi: float = Field(
        default=65.0,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MIN_RSI",
    )
    entry_quality_fallback_weak_volume_momentum_extension_max_rsi: float = Field(
        default=82.0,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MAX_RSI",
    )
    entry_quality_fallback_weak_volume_momentum_extension_min_sma20_distance: float = Field(
        default=0.12,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MIN_SMA20_DISTANCE",
    )
    entry_quality_fallback_weak_volume_momentum_extension_max_sma20_distance: float = Field(
        default=0.22,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MAX_SMA20_DISTANCE",
    )
    entry_quality_fallback_weak_volume_momentum_extension_min_volume_z: float = Field(
        default=-2.0,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MIN_VOLUME_Z",
    )
    entry_quality_fallback_weak_volume_momentum_extension_max_volume_z: float = Field(
        default=0.0,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MAX_VOLUME_Z",
    )
    entry_quality_fallback_weak_volume_momentum_extension_min_bullish_patterns: int = Field(
        default=1,
        alias="ENTRY_QUALITY_FALLBACK_WEAK_VOLUME_MOMENTUM_EXTENSION_MIN_BULLISH_PATTERNS",
    )
    entry_quality_fallback_relative_strength_pullback_extension_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_ENABLED",
    )
    entry_quality_fallback_relative_strength_pullback_extension_max_selection_rank: int = Field(
        default=10,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MAX_SELECTION_RANK",
    )
    entry_quality_fallback_relative_strength_pullback_extension_min_score: int = Field(
        default=15,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MIN_SCORE",
    )
    entry_quality_fallback_relative_strength_pullback_extension_min_return_20d: float = Field(
        default=0.30,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MIN_RETURN_20D",
    )
    entry_quality_fallback_relative_strength_pullback_extension_max_return_20d: float = Field(
        default=0.34,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MAX_RETURN_20D",
    )
    entry_quality_fallback_relative_strength_pullback_extension_min_relative_return_20d: float = Field(
        default=0.24,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MIN_RELATIVE_RETURN_20D",
    )
    entry_quality_fallback_relative_strength_pullback_extension_max_relative_return_20d: float = Field(
        default=0.28,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MAX_RELATIVE_RETURN_20D",
    )
    entry_quality_fallback_relative_strength_pullback_extension_min_rsi: float = Field(
        default=88.0,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MIN_RSI",
    )
    entry_quality_fallback_relative_strength_pullback_extension_max_rsi: float = Field(
        default=90.0,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MAX_RSI",
    )
    entry_quality_fallback_relative_strength_pullback_extension_min_sma20_distance: float = Field(
        default=0.18,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MIN_SMA20_DISTANCE",
    )
    entry_quality_fallback_relative_strength_pullback_extension_max_sma20_distance: float = Field(
        default=0.19,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MAX_SMA20_DISTANCE",
    )
    entry_quality_fallback_relative_strength_pullback_extension_min_volume_z: float = Field(
        default=-1.0,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MIN_VOLUME_Z",
    )
    entry_quality_fallback_relative_strength_pullback_extension_max_volume_z: float = Field(
        default=0.0,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MAX_VOLUME_Z",
    )
    entry_quality_fallback_relative_strength_pullback_extension_min_bullish_patterns: int = Field(
        default=1,
        alias="ENTRY_QUALITY_FALLBACK_RELATIVE_STRENGTH_PULLBACK_EXTENSION_MIN_BULLISH_PATTERNS",
    )
    entry_quality_fallback_leader_pullback_extension_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_ENABLED",
    )
    entry_quality_fallback_leader_pullback_extension_max_selection_rank: int = Field(
        default=8,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MAX_SELECTION_RANK",
    )
    entry_quality_fallback_leader_pullback_extension_min_score: int = Field(
        default=15,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MIN_SCORE",
    )
    entry_quality_fallback_leader_pullback_extension_min_return_20d: float = Field(
        default=0.40,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MIN_RETURN_20D",
    )
    entry_quality_fallback_leader_pullback_extension_max_return_20d: float = Field(
        default=0.46,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MAX_RETURN_20D",
    )
    entry_quality_fallback_leader_pullback_extension_min_rsi: float = Field(
        default=75.0,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MIN_RSI",
    )
    entry_quality_fallback_leader_pullback_extension_max_rsi: float = Field(
        default=82.0,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MAX_RSI",
    )
    entry_quality_fallback_leader_pullback_extension_min_sma20_distance: float = Field(
        default=0.25,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MIN_SMA20_DISTANCE",
    )
    entry_quality_fallback_leader_pullback_extension_max_sma20_distance: float = Field(
        default=0.28,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MAX_SMA20_DISTANCE",
    )
    entry_quality_fallback_leader_pullback_extension_min_volume_z: float = Field(
        default=-2.0,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MIN_VOLUME_Z",
    )
    entry_quality_fallback_leader_pullback_extension_max_volume_z: float = Field(
        default=0.0,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MAX_VOLUME_Z",
    )
    entry_quality_fallback_leader_pullback_extension_min_bullish_patterns: int = Field(
        default=1,
        alias="ENTRY_QUALITY_FALLBACK_LEADER_PULLBACK_EXTENSION_MIN_BULLISH_PATTERNS",
    )
    entry_quality_fallback_top_long_follow_through_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_ENABLED",
    )
    entry_quality_fallback_top_long_follow_through_max_selection_rank: int = Field(
        default=20,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MAX_SELECTION_RANK",
    )
    entry_quality_fallback_top_long_follow_through_min_score: int = Field(
        default=15,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MIN_SCORE",
    )
    entry_quality_fallback_top_long_follow_through_min_return_20d: float = Field(
        default=0.14,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MIN_RETURN_20D",
    )
    entry_quality_fallback_top_long_follow_through_max_return_20d: float = Field(
        default=0.18,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MAX_RETURN_20D",
    )
    entry_quality_fallback_top_long_follow_through_min_rsi: float = Field(
        default=66.0,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MIN_RSI",
    )
    entry_quality_fallback_top_long_follow_through_max_rsi: float = Field(
        default=72.0,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MAX_RSI",
    )
    entry_quality_fallback_top_long_follow_through_min_volume_z: float = Field(
        default=-2.75,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MIN_VOLUME_Z",
    )
    entry_quality_fallback_top_long_follow_through_max_volume_z: float = Field(
        default=0.0,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MAX_VOLUME_Z",
    )
    entry_quality_fallback_top_long_follow_through_min_bullish_patterns: int = Field(
        default=1,
        alias="ENTRY_QUALITY_FALLBACK_TOP_LONG_FOLLOW_THROUGH_MIN_BULLISH_PATTERNS",
    )
    entry_quality_prior_error_volume_confirmation_override_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_ENABLED",
    )
    entry_quality_prior_error_volume_confirmation_override_max_selection_rank: int = Field(
        default=5,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_MAX_SELECTION_RANK",
    )
    entry_quality_prior_error_volume_confirmation_override_min_score: int = Field(
        default=16,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_MIN_SCORE",
    )
    entry_quality_prior_error_volume_confirmation_override_min_return_20d: float = Field(
        default=0.30,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_MIN_RETURN_20D",
    )
    entry_quality_prior_error_volume_confirmation_override_min_rsi: float = Field(
        default=80.0,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_MIN_RSI",
    )
    entry_quality_prior_error_volume_confirmation_override_max_rsi: float = Field(
        default=85.0,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_MAX_RSI",
    )
    entry_quality_prior_error_volume_confirmation_override_min_volume_z: float = Field(
        default=1.5,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_MIN_VOLUME_Z",
    )
    entry_quality_prior_error_volume_confirmation_override_min_bullish_patterns: int = Field(
        default=1,
        alias="ENTRY_QUALITY_PRIOR_ERROR_VOLUME_CONFIRMATION_OVERRIDE_MIN_BULLISH_PATTERNS",
    )
    entry_quality_low_score_volume_rebound_override_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_OVERRIDE_ENABLED",
    )
    entry_quality_low_score_volume_rebound_min_score: int = Field(
        default=8,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MIN_SCORE",
    )
    entry_quality_low_score_volume_rebound_max_score: int = Field(
        default=9,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MAX_SCORE",
    )
    entry_quality_low_score_volume_rebound_max_selection_rank: int = Field(
        default=8,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MAX_SELECTION_RANK",
    )
    entry_quality_low_score_volume_rebound_min_return_20d: float = Field(
        default=0.08,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MIN_RETURN_20D",
    )
    entry_quality_low_score_volume_rebound_max_return_20d: float = Field(
        default=0.14,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MAX_RETURN_20D",
    )
    entry_quality_low_score_volume_rebound_min_rsi: float = Field(
        default=35.0,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MIN_RSI",
    )
    entry_quality_low_score_volume_rebound_max_rsi: float = Field(
        default=42.0,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MAX_RSI",
    )
    entry_quality_low_score_volume_rebound_min_volume_z: float = Field(
        default=1.0,
        alias="ENTRY_QUALITY_LOW_SCORE_VOLUME_REBOUND_MIN_VOLUME_Z",
    )
    entry_score_v2_enabled: bool = Field(default=True, alias="ENTRY_SCORE_V2_ENABLED")
    entry_score_v2_min: float = Field(default=0.52, alias="ENTRY_SCORE_V2_MIN")
    entry_score_v2_micro_min: float = Field(default=0.46, alias="ENTRY_SCORE_V2_MICRO_MIN")
    entry_score_v2_min_reward_risk: float = Field(default=1.5, alias="ENTRY_SCORE_V2_MIN_REWARD_RISK")
    entry_score_v2_reward_risk_margin_override_enabled: bool = Field(
        default=True,
        alias="ENTRY_SCORE_V2_REWARD_RISK_MARGIN_OVERRIDE_ENABLED",
    )
    entry_score_v2_reward_risk_margin_tolerance: float = Field(
        default=0.02,
        alias="ENTRY_SCORE_V2_REWARD_RISK_MARGIN_TOLERANCE",
    )
    entry_score_v2_reward_risk_override_max_selection_rank: int = Field(
        default=8,
        alias="ENTRY_SCORE_V2_REWARD_RISK_OVERRIDE_MAX_SELECTION_RANK",
    )
    entry_score_v2_reward_risk_override_min_score: int = Field(
        default=13,
        alias="ENTRY_SCORE_V2_REWARD_RISK_OVERRIDE_MIN_SCORE",
    )
    entry_score_v2_reward_risk_override_min_return_20d: float = Field(
        default=0.20,
        alias="ENTRY_SCORE_V2_REWARD_RISK_OVERRIDE_MIN_RETURN_20D",
    )
    entry_score_v2_reward_risk_override_min_rsi: float = Field(
        default=74.0,
        alias="ENTRY_SCORE_V2_REWARD_RISK_OVERRIDE_MIN_RSI",
    )
    entry_score_v2_reward_risk_override_max_sma20_distance: float = Field(
        default=0.30,
        alias="ENTRY_SCORE_V2_REWARD_RISK_OVERRIDE_MAX_SMA20_DISTANCE",
    )
    entry_score_v2_reward_risk_follow_through_override_enabled: bool = Field(
        default=True,
        alias="ENTRY_SCORE_V2_REWARD_RISK_FOLLOW_THROUGH_OVERRIDE_ENABLED",
    )
    entry_score_v2_reward_risk_follow_through_max_selection_rank: int = Field(
        default=15,
        alias="ENTRY_SCORE_V2_REWARD_RISK_FOLLOW_THROUGH_MAX_SELECTION_RANK",
    )
    entry_score_v2_reward_risk_follow_through_min_score: int = Field(
        default=14,
        alias="ENTRY_SCORE_V2_REWARD_RISK_FOLLOW_THROUGH_MIN_SCORE",
    )
    entry_score_v2_reward_risk_follow_through_min_return_20d: float = Field(
        default=0.06,
        alias="ENTRY_SCORE_V2_REWARD_RISK_FOLLOW_THROUGH_MIN_RETURN_20D",
    )
    entry_score_v2_reward_risk_follow_through_min_rsi: float = Field(
        default=65.0,
        alias="ENTRY_SCORE_V2_REWARD_RISK_FOLLOW_THROUGH_MIN_RSI",
    )
    entry_score_v2_reward_risk_follow_through_max_sma20_distance: float = Field(
        default=0.10,
        alias="ENTRY_SCORE_V2_REWARD_RISK_FOLLOW_THROUGH_MAX_SMA20_DISTANCE",
    )
    entry_score_v2_reward_risk_follow_through_min_confirmed_patterns: int = Field(
        default=2,
        alias="ENTRY_SCORE_V2_REWARD_RISK_FOLLOW_THROUGH_MIN_CONFIRMED_PATTERNS",
    )
    entry_score_v2_late_constructive_follow_through_override_enabled: bool = Field(
        default=True,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_OVERRIDE_ENABLED",
    )
    entry_score_v2_late_constructive_follow_through_min_selection_rank: int = Field(
        default=16,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MIN_SELECTION_RANK",
    )
    entry_score_v2_late_constructive_follow_through_max_selection_rank: int = Field(
        default=20,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MAX_SELECTION_RANK",
    )
    entry_score_v2_late_constructive_follow_through_min_score: int = Field(
        default=14,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MIN_SCORE",
    )
    entry_score_v2_late_constructive_follow_through_min_return_20d: float = Field(
        default=0.06,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MIN_RETURN_20D",
    )
    entry_score_v2_late_constructive_follow_through_max_return_20d: float = Field(
        default=0.09,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MAX_RETURN_20D",
    )
    entry_score_v2_late_constructive_follow_through_min_rsi: float = Field(
        default=65.0,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MIN_RSI",
    )
    entry_score_v2_late_constructive_follow_through_max_rsi: float = Field(
        default=72.0,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MAX_RSI",
    )
    entry_score_v2_late_constructive_follow_through_min_volume_z: float = Field(
        default=-2.2,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MIN_VOLUME_Z",
    )
    entry_score_v2_late_constructive_follow_through_max_volume_z: float = Field(
        default=-1.0,
        alias="ENTRY_SCORE_V2_LATE_CONSTRUCTIVE_FOLLOW_THROUGH_MAX_VOLUME_Z",
    )
    entry_quality_missing_relative_strength_follow_through_enabled: bool = Field(
        default=True,
        alias="ENTRY_QUALITY_MISSING_RELATIVE_STRENGTH_FOLLOW_THROUGH_ENABLED",
    )
    entry_quality_missing_relative_strength_follow_through_max_selection_rank: int = Field(
        default=18,
        alias="ENTRY_QUALITY_MISSING_RELATIVE_STRENGTH_FOLLOW_THROUGH_MAX_SELECTION_RANK",
    )
    entry_quality_missing_relative_strength_follow_through_min_score: int = Field(
        default=15,
        alias="ENTRY_QUALITY_MISSING_RELATIVE_STRENGTH_FOLLOW_THROUGH_MIN_SCORE",
    )
    entry_quality_missing_relative_strength_follow_through_min_return_20d: float = Field(
        default=0.11,
        alias="ENTRY_QUALITY_MISSING_RELATIVE_STRENGTH_FOLLOW_THROUGH_MIN_RETURN_20D",
    )
    entry_quality_missing_relative_strength_follow_through_min_rsi: float = Field(
        default=66.0,
        alias="ENTRY_QUALITY_MISSING_RELATIVE_STRENGTH_FOLLOW_THROUGH_MIN_RSI",
    )
    entry_quality_missing_relative_strength_follow_through_max_sma20_distance: float = Field(
        default=0.10,
        alias="ENTRY_QUALITY_MISSING_RELATIVE_STRENGTH_FOLLOW_THROUGH_MAX_SMA20_DISTANCE",
    )
    entry_quality_missing_relative_strength_follow_through_min_confirmed_patterns: int = Field(
        default=2,
        alias="ENTRY_QUALITY_MISSING_RELATIVE_STRENGTH_FOLLOW_THROUGH_MIN_CONFIRMED_PATTERNS",
    )
    micro_experiment_size_multiplier: float = Field(default=0.50, alias="MICRO_EXPERIMENT_SIZE_MULTIPLIER")
    backtest_gate_paper_soft_override_enabled: bool = Field(
        default=True,
        alias="BACKTEST_GATE_PAPER_SOFT_OVERRIDE_ENABLED",
    )
    backtest_gate_near_miss_shadow_enabled: bool = Field(
        default=True,
        alias="BACKTEST_GATE_NEAR_MISS_SHADOW_ENABLED",
    )
    exit_policy_v2_enabled: bool = Field(default=True, alias="EXIT_POLICY_V2_ENABLED")
    exit_policy_v2_partial_r: float = Field(default=1.0, alias="EXIT_POLICY_V2_PARTIAL_R")
    exit_policy_v2_trailing_r: float = Field(default=2.0, alias="EXIT_POLICY_V2_TRAILING_R")
    exit_policy_v2_trailing_giveback_r: float = Field(default=1.0, alias="EXIT_POLICY_V2_TRAILING_GIVEBACK_R")
    exit_policy_v2_time_stop_days: int = Field(default=5, alias="EXIT_POLICY_V2_TIME_STOP_DAYS")
    exit_policy_v2_time_stop_min_return: float = Field(default=0.0, alias="EXIT_POLICY_V2_TIME_STOP_MIN_RETURN")
    exit_policy_v2_stale_guard_enabled: bool = Field(default=False, alias="EXIT_POLICY_V2_STALE_GUARD_ENABLED")
    exit_policy_v2_stale_guard_days: int = Field(default=10, alias="EXIT_POLICY_V2_STALE_GUARD_DAYS")
    exit_policy_v2_stale_guard_max_peak_return: float = Field(
        default=0.05,
        alias="EXIT_POLICY_V2_STALE_GUARD_MAX_PEAK_RETURN",
    )
    exit_policy_v2_stale_guard_min_return: float = Field(
        default=0.01,
        alias="EXIT_POLICY_V2_STALE_GUARD_MIN_RETURN",
    )
    auto_paper_trading: bool = Field(default=False, alias="AUTO_PAPER_TRADING")
    require_human_approval: bool = Field(default=True, alias="REQUIRE_HUMAN_APPROVAL")
    deterministic_trade_fallback_enabled: bool = Field(
        default=True,
        alias="DETERMINISTIC_TRADE_FALLBACK_ENABLED",
    )
    # T2b/F3: reordenar los candidatos del fallback determinista por score de
    # oportunidad (fuerza relativa / momentum / tendencia). Reversible por flag.
    opportunity_ranker_fallback_enabled: bool = Field(
        default=True,
        alias="OPPORTUNITY_RANKER_FALLBACK_ENABLED",
    )
    selection_negative_pocket_penalty_enabled: bool = Field(
        default=True,
        alias="SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED",
    )
    selection_negative_pocket_confirmed_pattern_penalty: float = Field(
        default=0.050,
        alias="SELECTION_NEGATIVE_POCKET_CONFIRMED_PATTERN_PENALTY",
    )
    selection_negative_pocket_weak_volume_penalty: float = Field(
        default=0.025,
        alias="SELECTION_NEGATIVE_POCKET_WEAK_VOLUME_PENALTY",
    )
    selection_negative_pocket_tight_sma20_penalty: float = Field(
        default=0.030,
        alias="SELECTION_NEGATIVE_POCKET_TIGHT_SMA20_PENALTY",
    )
    selection_negative_pocket_mid_rsi_penalty: float = Field(
        default=0.020,
        alias="SELECTION_NEGATIVE_POCKET_MID_RSI_PENALTY",
    )
    max_risk_per_trade: float = Field(default=0.01, alias="MAX_RISK_PER_TRADE")
    max_total_open_risk: float = Field(default=0.03, alias="MAX_TOTAL_OPEN_RISK")
    max_orders_per_cycle: int = Field(default=4, alias="MAX_ORDERS_PER_CYCLE")
    max_daily_buy_orders: int = Field(default=4, alias="MAX_DAILY_BUY_ORDERS")
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
    # Ciclo de vida del laboratorio (Etapa 7): TTL, WIP y cierre de iniciativas.
    ci_task_ttl_hours: float = Field(default=48.0, alias="CI_TASK_TTL_HOURS")
    ci_initiative_ttl_days: float = Field(default=5.0, alias="CI_INITIATIVE_TTL_DAYS")
    ci_validation_backlog_ttl_days: float = Field(default=2.0, alias="CI_VALIDATION_BACKLOG_TTL_DAYS")
    ci_initiative_stall_days: float = Field(default=3.0, alias="CI_INITIATIVE_STALL_DAYS")
    ci_monitoring_close_days: float = Field(default=5.0, alias="CI_MONITORING_CLOSE_DAYS")
    ci_max_open_initiatives: int = Field(default=4, alias="CI_MAX_OPEN_INITIATIVES")
    ci_recurring_cooldown_hours: float = Field(default=24.0, alias="CI_RECURRING_COOLDOWN_HOURS")
    improvement_llm_local_fallback_enabled: bool = Field(
        default=True,
        alias="IMPROVEMENT_LLM_LOCAL_FALLBACK_ENABLED",
    )
    improvement_llm_context_target_tokens: int = Field(
        default=40000,
        alias="IMPROVEMENT_LLM_CONTEXT_TARGET_TOKENS",
    )
    improvement_llm_context_hard_limit_tokens: int = Field(
        default=55000,
        alias="IMPROVEMENT_LLM_CONTEXT_HARD_LIMIT_TOKENS",
    )
    improvement_llm_local_context_target_tokens: int = Field(
        default=30000,
        alias="IMPROVEMENT_LLM_LOCAL_CONTEXT_TARGET_TOKENS",
    )
    improvement_llm_local_context_hard_limit_tokens: int = Field(
        default=50000,
        alias="IMPROVEMENT_LLM_LOCAL_CONTEXT_HARD_LIMIT_TOKENS",
    )
    improvement_dry_run: bool = Field(default=False, alias="IMPROVEMENT_DRY_RUN")
    allow_auto_apply_improvements: bool = Field(default=True, alias="ALLOW_AUTO_APPLY_IMPROVEMENTS")
    require_human_approval_for_code_changes: bool = Field(
        default=False,
        alias="REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES",
    )
    require_human_approval_for_high_risk: bool = Field(
        default=True,
        alias="REQUIRE_HUMAN_APPROVAL_FOR_HIGH_RISK",
    )
    ci_sandbox_enabled: bool = Field(default=True, alias="CI_SANDBOX_ENABLED")
    ci_sandbox_full_suite: bool = Field(default=True, alias="CI_SANDBOX_FULL_SUITE")
    ci_sandbox_validate_timeout_seconds: int = Field(
        default=900,
        alias="CI_SANDBOX_VALIDATE_TIMEOUT_SECONDS",
    )
    # Watchdog de cambios aplicados (T0.5): vigila las metricas tras cada cambio
    # promovido y revierte solo si empeoran.
    change_watchdog_enabled: bool = Field(default=True, alias="CHANGE_WATCHDOG_ENABLED")
    change_watchdog_window_sessions: int = Field(default=5, alias="CHANGE_WATCHDOG_WINDOW_SESSIONS")
    change_watchdog_max_iq_drop: float = Field(default=10.0, alias="CHANGE_WATCHDOG_MAX_IQ_DROP")
    change_watchdog_max_hit_rate_drop: float = Field(default=0.15, alias="CHANGE_WATCHDOG_MAX_HIT_RATE_DROP")
    change_watchdog_min_trades: int = Field(default=5, alias="CHANGE_WATCHDOG_MIN_TRADES")
    # Niveles de autonomia de codigo (T1.1). El nivel sube/baja solo segun el
    # historial; CODE_AUTONOMY_LEVEL es el suelo/arranque.
    code_autonomy_level: int = Field(default=1, alias="CODE_AUTONOMY_LEVEL")
    autonomy_promotion_min_applied: int = Field(default=10, alias="AUTONOMY_PROMOTION_MIN_APPLIED")
    autonomy_promotion_clean_sessions: int = Field(default=15, alias="AUTONOMY_PROMOTION_CLEAN_SESSIONS")
    autonomy_demote_rollbacks: int = Field(default=2, alias="AUTONOMY_DEMOTE_ROLLBACKS")
    autonomy_demote_sessions: int = Field(default=10, alias="AUTONOMY_DEMOTE_SESSIONS")
    # Promocion champion/challenger de estrategias (T1.3).
    promotion_min_sessions: int = Field(default=25, alias="PROMOTION_MIN_SESSIONS")  # T5.2
    promotion_min_signals: int = Field(default=40, alias="PROMOTION_MIN_SIGNALS")  # T5.2
    promotion_max_sessions: int = Field(default=45, alias="PROMOTION_MAX_SESSIONS")  # T5.2
    promotion_hit_rate_margin: float = Field(default=0.02, alias="PROMOTION_HIT_RATE_MARGIN")
    promotion_max_dd_factor: float = Field(default=1.2, alias="PROMOTION_MAX_DD_FACTOR")
    promotion_human_veto_hours: int = Field(default=0, alias="PROMOTION_HUMAN_VETO_HOURS")
    promotion_binomial_max_p: float = Field(default=0.10, alias="PROMOTION_BINOMIAL_MAX_P")  # T5.2
    max_concurrent_promotions: int = Field(default=2, alias="MAX_CONCURRENT_PROMOTIONS")  # T5.2
    max_promotions_per_week: int = Field(default=1, alias="MAX_PROMOTIONS_PER_WEEK")  # T5.2
    # ProgrammerAgent end-to-end / construccion de estrategias (T1.4).
    ci_build_strategy_enabled: bool = Field(default=False, alias="CI_BUILD_STRATEGY_ENABLED")
    programmer_max_repair_attempts: int = Field(default=2, alias="PROGRAMMER_MAX_REPAIR_ATTEMPTS")
    # Auto-edicion de prompts por el laboratorio (T2.1).
    prompt_self_edit_enabled: bool = Field(default=False, alias="PROMPT_SELF_EDIT_ENABLED")
    # Retrospectiva generativa nocturna (T2.3).
    nightly_retrospective_enabled: bool = Field(default=True, alias="NIGHTLY_RETROSPECTIVE_ENABLED")
    nightly_retrospective_min_evidence: int = Field(default=3, alias="NIGHTLY_RETROSPECTIVE_MIN_EVIDENCE")
    # Memoria destilada / lecciones (T2.4 / T5.4).
    lessons_injection_enabled: bool = Field(default=True, alias="LESSONS_INJECTION_ENABLED")
    max_active_lessons: int = Field(default=40, alias="MAX_ACTIVE_LESSONS")
    lesson_revalidation_window: int = Field(default=10, alias="LESSON_REVALIDATION_WINDOW")
    lesson_min_supporting: int = Field(default=30, alias="LESSON_MIN_SUPPORTING")  # T5.4
    # Fabrica de agentes dinamicos (T2.2).
    max_dynamic_agents: int = Field(default=8, alias="MAX_DYNAMIC_AGENTS")
    # Tesis de mercado / contexto macro (T3.1).
    macro_thesis_enabled: bool = Field(default=True, alias="MACRO_THESIS_ENABLED")
    risk_off_buy_factor: float = Field(default=0.5, alias="RISK_OFF_BUY_FACTOR")
    risk_off_confidence_threshold: float = Field(default=0.7, alias="RISK_OFF_CONFIDENCE_THRESHOLD")
    # Evidencia externa de investigacion y frescura de fuentes.
    research_evidence_enabled: bool = Field(default=True, alias="RESEARCH_EVIDENCE_ENABLED")
    research_evidence_fail_closed_for_buys: bool = Field(
        default=True,
        alias="RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS",
    )
    research_evidence_max_age_hours: float = Field(default=48.0, alias="RESEARCH_EVIDENCE_MAX_AGE_HOURS")
    research_evidence_min_reliability: float = Field(default=0.45, alias="RESEARCH_EVIDENCE_MIN_RELIABILITY")
    # Fabrica de hipotesis + granja de backtests (T3.2).
    factory_max_variants_per_night: int = Field(default=50, alias="FACTORY_MAX_VARIANTS_PER_NIGHT")
    factory_workers: int = Field(default=4, alias="FACTORY_WORKERS")
    factory_max_minutes: int = Field(default=60, alias="FACTORY_MAX_MINUTES")
    # Scorecard de figuras con pesos dinamicos (T3.3).
    pattern_dynamic_weights_enabled: bool = Field(default=False, alias="PATTERN_DYNAMIC_WEIGHTS_ENABLED")
    pattern_min_occurrences: int = Field(default=30, alias="PATTERN_MIN_OCCURRENCES")
    survivorship_haircut: float = Field(default=0.25, alias="SURVIVORSHIP_HAIRCUT")  # T5.6
    # Presupuesto de riesgo como unica correa (T4.1).
    risk_budget_enabled: bool = Field(default=False, alias="RISK_BUDGET_ENABLED")
    risk_budget_daily_var_pct: float = Field(default=0.03, alias="RISK_BUDGET_DAILY_VAR_PCT")
    risk_budget_max_new_risk_per_day_pct: float = Field(default=0.015, alias="RISK_BUDGET_MAX_NEW_RISK_PER_DAY_PCT")
    risk_budget_max_correlated_cluster_pct: float = Field(default=0.012, alias="RISK_BUDGET_MAX_CORRELATED_CLUSTER_PCT")
    # Camino a live con capital progresivo (T4.3).
    live_capital_fraction: float = Field(default=0.10, alias="LIVE_CAPITAL_FRACTION")
    # Etapa 5: robustez de trading.
    system_freeze_mode: bool = Field(default=False, alias="SYSTEM_FREEZE_MODE")  # T5.1
    # Cash activo y estrategias por regimen (T5.7).
    cash_floor_risk_off: float = Field(default=0.60, alias="CASH_FLOOR_RISK_OFF")
    cash_floor_neutral: float = Field(default=0.25, alias="CASH_FLOOR_NEUTRAL")
    factory_regime_quota: float = Field(default=0.30, alias="FACTORY_REGIME_QUOTA")
    shorts_shadow_enabled: bool = Field(default=True, alias="SHORTS_SHADOW_ENABLED")
    # Huecos operativos: earnings/splits/halts (T5.10).
    earnings_hold_max_days: int = Field(default=2, alias="EARNINGS_HOLD_MAX_DAYS")
    earnings_hold_policy: str = Field(default="reduce", alias="EARNINGS_HOLD_POLICY")
    # Realismo de ejecucion (T5.5).
    paper_synthetic_slippage_bps: float = Field(default=10.0, alias="PAPER_SYNTHETIC_SLIPPAGE_BPS")
    max_entry_gap_pct: float = Field(default=0.015, alias="MAX_ENTRY_GAP_PCT")
    use_limit_entries: bool = Field(default=True, alias="USE_LIMIT_ENTRIES")
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
    continuous_improvement_group_cooldown_seconds: int = Field(
        default=300,
        alias="CONTINUOUS_IMPROVEMENT_GROUP_COOLDOWN_SECONDS",
    )
    continuous_improvement_event_cooldown_seconds: int = Field(
        default=1800,
        alias="CONTINUOUS_IMPROVEMENT_EVENT_COOLDOWN_SECONDS",
    )
    continuous_improvement_runtime_loop_sleep_seconds: int = Field(
        default=15,
        alias="CONTINUOUS_IMPROVEMENT_RUNTIME_LOOP_SLEEP_SECONDS",
    )
    continuous_improvement_retry_base_seconds: int = Field(
        default=180,
        alias="CONTINUOUS_IMPROVEMENT_RETRY_BASE_SECONDS",
    )
    continuous_improvement_retry_max_seconds: int = Field(
        default=900,
        alias="CONTINUOUS_IMPROVEMENT_RETRY_MAX_SECONDS",
    )
    continuous_improvement_max_proposals_per_cycle: int = Field(
        default=5,
        alias="CONTINUOUS_IMPROVEMENT_MAX_PROPOSALS_PER_CYCLE",
    )
    continuous_improvement_workspace_dir: Path | None = Field(
        default=None,
        alias="CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR",
    )
    overnight_learning_enabled: bool = Field(default=True, alias="OVERNIGHT_LEARNING_ENABLED")
    overnight_learning_use_llm: bool = Field(default=True, alias="OVERNIGHT_LEARNING_USE_LLM")
    overnight_learning_time_local: str = Field(default="00:10", alias="OVERNIGHT_LEARNING_TIME_LOCAL")
    overnight_learning_stale_llm_alert_hours: float = Field(
        default=24.0,
        alias="OVERNIGHT_LEARNING_STALE_LLM_ALERT_HOURS",
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
    agents_healthcheck_interval_minutes: int = Field(
        default=30,
        alias="AGENTS_HEALTHCHECK_INTERVAL_MINUTES",
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
    selection_leader_momentum_min_score: int = Field(
        default=11,
        alias="SELECTION_LEADER_MOMENTUM_MIN_SCORE",
    )
    selection_leader_momentum_min_relative_return_20d: float = Field(
        default=0.16,
        alias="SELECTION_LEADER_MOMENTUM_MIN_RELATIVE_RETURN_20D",
    )
    selection_leader_momentum_min_bullish_patterns: int = Field(
        default=1,
        alias="SELECTION_LEADER_MOMENTUM_MIN_BULLISH_PATTERNS",
    )
    selection_leader_momentum_max_sma20_distance: float = Field(
        default=0.33,
        alias="SELECTION_LEADER_MOMENTUM_MAX_SMA20_DISTANCE",
    )
    selection_leader_momentum_max_rsi: float = Field(
        default=86.0,
        alias="SELECTION_LEADER_MOMENTUM_MAX_RSI",
    )
    selection_leader_momentum_min_close_position_in_range: float = Field(
        default=0.35,
        alias="SELECTION_LEADER_MOMENTUM_MIN_CLOSE_POSITION_IN_RANGE",
    )
    selection_leader_momentum_min_volume_z: float = Field(
        default=-3.0,
        alias="SELECTION_LEADER_MOMENTUM_MIN_VOLUME_Z",
    )
    selection_leader_momentum_selection_bonus: float = Field(
        default=0.016,
        alias="SELECTION_LEADER_MOMENTUM_SELECTION_BONUS",
    )
    selection_leader_momentum_priority_bonus: float = Field(
        default=0.014,
        alias="SELECTION_LEADER_MOMENTUM_PRIORITY_BONUS",
    )
    selection_emerging_leader_min_score: int = Field(
        default=10,
        alias="SELECTION_EMERGING_LEADER_MIN_SCORE",
    )
    selection_emerging_leader_max_score: int = Field(
        default=11,
        alias="SELECTION_EMERGING_LEADER_MAX_SCORE",
    )
    selection_emerging_leader_min_return_20d: float = Field(
        default=0.08,
        alias="SELECTION_EMERGING_LEADER_MIN_RETURN_20D",
    )
    selection_emerging_leader_min_rsi: float = Field(
        default=75.0,
        alias="SELECTION_EMERGING_LEADER_MIN_RSI",
    )
    selection_emerging_leader_max_rsi: float = Field(
        default=86.0,
        alias="SELECTION_EMERGING_LEADER_MAX_RSI",
    )
    selection_emerging_leader_min_sma20_distance: float = Field(
        default=0.04,
        alias="SELECTION_EMERGING_LEADER_MIN_SMA20_DISTANCE",
    )
    selection_emerging_leader_max_sma20_distance: float = Field(
        default=0.15,
        alias="SELECTION_EMERGING_LEADER_MAX_SMA20_DISTANCE",
    )
    selection_emerging_leader_min_volume_z: float = Field(
        default=-3.0,
        alias="SELECTION_EMERGING_LEADER_MIN_VOLUME_Z",
    )
    selection_emerging_leader_max_volume_z: float = Field(
        default=3.0,
        alias="SELECTION_EMERGING_LEADER_MAX_VOLUME_Z",
    )
    selection_emerging_leader_min_close_position_in_range: float = Field(
        default=0.75,
        alias="SELECTION_EMERGING_LEADER_MIN_CLOSE_POSITION_IN_RANGE",
    )
    selection_emerging_leader_selection_bonus: float = Field(
        default=0.018,
        alias="SELECTION_EMERGING_LEADER_SELECTION_BONUS",
    )
    selection_emerging_leader_priority_bonus: float = Field(
        default=0.016,
        alias="SELECTION_EMERGING_LEADER_PRIORITY_BONUS",
    )
    selection_parabolic_leader_min_score: int = Field(
        default=14,
        alias="SELECTION_PARABOLIC_LEADER_MIN_SCORE",
    )
    selection_parabolic_leader_min_return_20d: float = Field(
        default=0.60,
        alias="SELECTION_PARABOLIC_LEADER_MIN_RETURN_20D",
    )
    selection_parabolic_leader_min_rsi: float = Field(
        default=85.0,
        alias="SELECTION_PARABOLIC_LEADER_MIN_RSI",
    )
    selection_parabolic_leader_max_rsi: float = Field(
        default=94.0,
        alias="SELECTION_PARABOLIC_LEADER_MAX_RSI",
    )
    selection_parabolic_leader_max_sma20_distance: float = Field(
        default=0.45,
        alias="SELECTION_PARABOLIC_LEADER_MAX_SMA20_DISTANCE",
    )
    selection_parabolic_leader_min_sma20_distance: float = Field(
        default=0.25,
        alias="SELECTION_PARABOLIC_LEADER_MIN_SMA20_DISTANCE",
    )
    selection_parabolic_leader_min_volume_z: float = Field(
        default=-3.0,
        alias="SELECTION_PARABOLIC_LEADER_MIN_VOLUME_Z",
    )
    selection_parabolic_leader_selection_bonus: float = Field(
        default=0.020,
        alias="SELECTION_PARABOLIC_LEADER_SELECTION_BONUS",
    )
    selection_parabolic_leader_priority_bonus: float = Field(
        default=0.018,
        alias="SELECTION_PARABOLIC_LEADER_PRIORITY_BONUS",
    )
    selection_top_long_alignment_max_rank: int = Field(
        default=10,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MAX_RANK",
    )
    selection_top_long_alignment_min_score: int = Field(
        default=14,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MIN_SCORE",
    )
    selection_top_long_alignment_min_bullish_patterns: int = Field(
        default=2,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MIN_BULLISH_PATTERNS",
    )
    selection_top_long_alignment_min_return_20d: float = Field(
        default=0.10,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MIN_RETURN_20D",
    )
    selection_top_long_alignment_max_return_20d: float = Field(
        default=0.22,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MAX_RETURN_20D",
    )
    selection_top_long_alignment_min_rsi: float = Field(
        default=65.0,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MIN_RSI",
    )
    selection_top_long_alignment_max_rsi: float = Field(
        default=72.0,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MAX_RSI",
    )
    selection_top_long_alignment_min_sma20_distance: float = Field(
        default=0.04,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MIN_SMA20_DISTANCE",
    )
    selection_top_long_alignment_max_sma20_distance: float = Field(
        default=0.10,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MAX_SMA20_DISTANCE",
    )
    selection_top_long_alignment_min_volume_z: float = Field(
        default=-3.0,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MIN_VOLUME_Z",
    )
    selection_top_long_alignment_max_volume_z: float = Field(
        default=0.5,
        alias="SELECTION_TOP_LONG_ALIGNMENT_MAX_VOLUME_Z",
    )
    selection_top_long_alignment_selection_bonus: float = Field(
        default=0.01,
        alias="SELECTION_TOP_LONG_ALIGNMENT_SELECTION_BONUS",
    )
    selection_top_long_alignment_priority_bonus: float = Field(
        default=0.008,
        alias="SELECTION_TOP_LONG_ALIGNMENT_PRIORITY_BONUS",
    )
    selection_constructive_early_min_score: int = Field(
        default=14,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_SCORE",
    )
    selection_constructive_early_max_score: int = Field(
        default=16,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MAX_SCORE",
    )
    selection_constructive_early_min_return_20d: float = Field(
        default=0.065,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_RETURN_20D",
    )
    selection_constructive_early_max_return_20d: float = Field(
        default=0.09,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MAX_RETURN_20D",
    )
    selection_constructive_early_min_return_60d: float = Field(
        default=0.03,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_RETURN_60D",
    )
    selection_constructive_early_max_return_60d: float = Field(
        default=0.14,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MAX_RETURN_60D",
    )
    selection_constructive_early_min_rsi: float = Field(
        default=65.0,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_RSI",
    )
    selection_constructive_early_max_rsi: float = Field(
        default=72.0,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MAX_RSI",
    )
    selection_constructive_early_min_sma20_distance: float = Field(
        default=0.055,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_SMA20_DISTANCE",
    )
    selection_constructive_early_max_sma20_distance: float = Field(
        default=0.08,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MAX_SMA20_DISTANCE",
    )
    selection_constructive_early_min_volume_z: float = Field(
        default=-2.3,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_VOLUME_Z",
    )
    selection_constructive_early_max_volume_z: float = Field(
        default=0.3,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MAX_VOLUME_Z",
    )
    selection_constructive_early_min_bollinger_pct_b: float = Field(
        default=0.85,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_BOLLINGER_PCT_B",
    )
    selection_constructive_early_min_bullish_patterns: int = Field(
        default=2,
        alias="SELECTION_CONSTRUCTIVE_EARLY_MIN_BULLISH_PATTERNS",
    )
    selection_constructive_early_selection_bonus: float = Field(
        default=0.014,
        alias="SELECTION_CONSTRUCTIVE_EARLY_SELECTION_BONUS",
    )
    selection_constructive_early_priority_bonus: float = Field(
        default=0.012,
        alias="SELECTION_CONSTRUCTIVE_EARLY_PRIORITY_BONUS",
    )
    breakout_extra_symbols: str = Field(default="", alias="BREAKOUT_EXTRA_SYMBOLS")
    intraday_news_sentiment_enabled: bool = Field(default=False, alias="INTRADAY_NEWS_SENTIMENT_ENABLED")
    news_sentiment_enabled: bool = Field(default=True, alias="NEWS_SENTIMENT_ENABLED")
    news_sentiment_top_n: int = Field(default=10, alias="NEWS_SENTIMENT_TOP_N")
    trade_selection_top_n: int = Field(default=24, alias="TRADE_SELECTION_TOP_N")
    news_items_per_symbol: int = Field(default=5, alias="NEWS_ITEMS_PER_SYMBOL")
    news_sentiment_fail_closed_for_buys: bool = Field(
        default=False,
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
        formal_data = self.market_data_provider == "fmp" or (
            self.market_data_provider == "auto" and bool(self.fmp_api_key)
        )
        if self.trading_mode == "live" and self.live_requires_formal_market_data and not formal_data:
            raise RuntimeError("Live trading bloqueado: configura FMP_API_KEY o MARKET_DATA_PROVIDER=fmp.")


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
