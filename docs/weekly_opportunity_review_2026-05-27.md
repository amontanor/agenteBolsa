# Weekly Opportunity Review - 2026-05-27

## Scope

This review uses the latest 7 market days with local evidence in `learning_observations`:

- 2026-05-22
- 2026-05-14
- 2026-05-13
- 2026-05-12
- 2026-05-11
- 2026-05-08
- 2026-05-07

The objective is to identify missed opportunities from the last week, explain why they were missed, and justify one conservative code change that would have made the system more likely to take at least one of the best missed trades without weakening safety.

## Filtering approach

The review keeps only canonical `learning_observations` that are:

- `direction = long`
- `setup_quality = strong`
- have a realized `return_5d`
- were not executed

Missed cases were classified as:

- `candidate_not_selected`
- `approved_not_executed`
- `blocked_entry_quality`
- `blocked_backtest`

Deduplication was done per `(signal_date, symbol)` using the strongest local observation.

## Main finding

The best missed opportunities from the last week were mostly **not blocked by risk or entry-quality**. They were **strong candidates that were never prioritized high enough before the LLM decision**.

That matters because it points to a ranking problem, not a safety problem.

## Best missed opportunities

### 1. CSCO

Most relevant missed name.

- 2026-05-11
  - `score = 19`
  - `rsi = 71.41`
  - `distance_sma20 = 10.02%`
  - `volume_zscore_20 = 2.75`
  - `confirmed_patterns = 2`
  - `decision = candidate_not_selected`
  - `return_5d = +20.42%`

- 2026-05-12
  - `score = 19`
  - `rsi = 72.04`
  - `distance_sma20 = 9.64%`
  - `volume_zscore_20 = 1.73`
  - `confirmed_patterns = 2`
  - `decision = candidate_not_selected`
  - `return_5d = +16.21%`

- 2026-05-08
  - `score = 16`
  - `rsi = 71.20`
  - `distance_sma20 = 8.61%`
  - `volume_zscore_20 = 1.56`
  - `confirmed_patterns = 2`
  - `decision = candidate_not_selected`
  - `return_5d = +22.41%`

Interpretation:

- no hard risk failure,
- no entry-quality veto,
- no backtest veto,
- repeated technical strength across several sessions,
- volume confirmation and confirmed bullish structure,
- but not promoted enough by the pre-LLM ranking.

This is the cleanest case for a conservative ranking improvement.

### 2. PANW

- 2026-05-11
  - `score = 17`
  - `rsi = 79.91`
  - `distance_sma20 = 18.24%`
  - `volume_zscore_20 = 1.36`
  - `confirmed_patterns = 2`
  - `decision = candidate_not_selected`
  - `return_5d = +15.86%`

- 2026-05-08
  - `score = 16`
  - `rsi = 79.79`
  - `distance_sma20 = 16.69%`
  - `volume_zscore_20 = 2.36`
  - `confirmed_patterns = 2`
  - `decision = candidate_not_selected`
  - `return_5d = +16.81%`

Interpretation:

- more extended than CSCO,
- still volume-confirmed and structurally strong,
- also missed by prioritization rather than by explicit safety blocks.

This reinforces the same structural lesson.

### 3. Cases intentionally not targeted by the change

Some very profitable misses existed, but they are not good targets for a conservative improvement:

- `COHR` on 2026-05-07: `score = 8`, no confirmed patterns.
- `MU` on 2026-05-07: `score = 12`, `distance_sma20 = 25.30%`, only 1 confirmed pattern.
- several `CRWD` cases: high return, but many had weak/negative volume confirmation or very extreme extension.

These cases would require either:

- lowering score discipline,
- relaxing safety more broadly,
- or accepting much higher extension risk.

That would move the system toward overfitting or lower safety, so they were rejected as change targets.

## Summary by missed bucket

From the deduped weekly sample:

- `candidate_not_selected`: 1399 cases, average `return_5d = -0.10%`, winner rate `38.38%`
- `approved_not_executed`: 1 case, `return_5d = +5.31%`
- `blocked_entry_quality`: 2 cases, average `return_5d = +1.67%`

Interpretation:

- most misses are noise,
- but the best missed names are concentrated in a recognizable subgroup,
- and that subgroup was being under-promoted rather than hard-blocked.

## Chosen code change

The implemented change adds a conservative ranking bonus for:

- `score >= 17`
- `volume_zscore_20 >= 1.25`
- `confirmed_patterns >= 2`
- `breakout_failure_risk = false`
- `distance_sma20` between `4%` and `20%`
- `rsi_14` between `65` and `82`

This pattern is labeled:

- `high_conviction_confirmed_momentum`

It is applied only in:

- `selection_score`
- `rank_priority_score`

It is **not** applied by relaxing:

- `entry_quality`
- stop-loss rules
- take-profit rules
- max position exposure
- max total risk
- auto-buy shadow-only setup policy

## Why this is conservative

The change does not let weaker names in.

It only reorders already strong candidates when they also have:

- high score,
- positive volume confirmation,
- confirmed bullish structure,
- no breakout failure,
- extension inside a bounded range,
- RSI that is hot but not absurd.

This is consistent with the last week's missed `CSCO` pattern and also captures `PANW`-like behavior without opening the system to low-score or highly speculative names.

## Evidence of alignment

Representative opportunity aligned with the new logic:

- `CSCO`, 2026-05-11
  - strong score
  - positive volume confirmation
  - two confirmed bullish patterns
  - controlled extension
  - no explicit safety veto

That is exactly the kind of case the new selector should promote.

## Verification

Relevant selector test added:

- `test_select_deterministic_candidates_promotes_high_conviction_confirmed_momentum`

Status:

- `tests/test_trade_decision.py`: passed

Full suite status at review time:

- `220 passed`
- `1 failed` in `test_web_app.py`

The failing web-app test is unrelated to the selector change.
