# Daily Opportunity Review - 2026-05-28

## Scope

This review studies the trading session of `2026-05-28`, which was not launched.

The objective is:

1. estimate what the system would have been likely to do with the current code and current learning state,
2. estimate whether there was a credible path to an additional `+1%`,
3. identify only conservative changes supported by local evidence.

This review uses:

- `data/reports/latest_closed_market_technical_study.json`
- `data/reports/latest_daily_learning_digest.json`
- `data/reports/latest_operational_health.json`
- current code in `trade_decision.py` and `config.py`

## Important context

Today is materially different from the last weekly review.

On `2026-05-28`, the operational response layer is actively penalizing:

- `confirmed_pattern`
- `baseline_trend`
- `trend_volume`

with `candidate_priority_penalty = 0.05`.

That matters because most of today's long candidates belong to `confirmed_pattern`, and many of them are:

- very extended above `SMA20`,
- high RSI,
- weak or negative relative volume.

So the raw technical list looks stronger than the effective post-learning list.

## Current operating limits

Relevant live limits in current code:

- `MAX_POSITION_EXPOSURE = 0.05`
- `MAX_ORDERS_PER_CYCLE = 3`
- `MAX_DAILY_BUY_ORDERS = 3`
- `ENTRY_QUALITY_MIN_SCORE = 12`
- `ENTRY_QUALITY_MAX_SMA20_DISTANCE = 0.12`
- `ENTRY_QUALITY_MAX_RSI = 85`

These limits imply that even a good day rarely converts into `+1%` expected portfolio gain unless there are several high-quality names or position size is increased.

## What the technical study produced today

From the latest closed-market study:

- `symbols_scanned = 500`
- `symbols_with_data = 499`
- `eligible long strong candidates = 226`

The raw score-driven top of the book is dominated by names such as:

- `FSLR`
- `BBY`
- `SNDK`
- `TER`
- `LRCX`
- `DOC`
- `HPE`

But those names are not equally actionable.

## What the deterministic selector says today

Rebuilding the selector logic with the current learning digest and the active operational penalty gives this picture.

### Top by raw score

Top names by current raw score:

1. `FSLR`
2. `BBY`
3. `SNDK`

Average shrunk edge of the top 3:

- `-0.32%` over the modeled short horizon

With `3` positions at `5%` each, that is approximately:

- `-0.05%` expected portfolio effect

### Top by deterministic selection score

Top names by current deterministic selection score:

1. `BBY`
2. `RVTY`
3. `DLTR`

Average shrunk edge of the top 3:

- `-0.09%`

Approximate portfolio effect at current sizing:

- `-0.01%`

### Interpretation

The deterministic selector is still better than pure score today, but only marginally.

Estimated delta versus the raw score basket:

- about `+0.23 pp` on the position basket
- about `+0.03 pp` at portfolio level with current sizing

That is nowhere near a robust `+1%`.

## The only clear high-conviction subgroup today

If we search for candidates with all of the following:

- `score >= 14`
- `volume_zscore_20 >= 1.0`
- at least `1` confirmed bullish pattern

only one name stands out:

- `BBY`

Today `BBY` looks like this:

- `score = 16`
- `setup = breakout_continuation`
- `return_20d = +28.88%`
- `relative_return_20d = +22.88%`
- `RSI = 83.35`
- `volume_zscore_20 = 1.79`
- `distance_sma20 = +26.18%`
- `confirmed bullish patterns = 2`
- `close_position_in_range = 0.994`

This is the only name that looks like a real momentum continuation instead of a generic extended `confirmed_pattern`.

## Why BBY still does not justify an active change

`BBY` is blocked by the current `entry_quality` logic for a good reason:

- it is far beyond `ENTRY_QUALITY_MAX_SMA20_DISTANCE = 0.12`
- it is also beyond the `0.22` ceiling used in the existing special cases
- `breakout_continuation` does not currently have its own extension exception

To allow `BBY`, we would need to add a new exception for `breakout_continuation` and relax the allowed extension far above the current conservative range.

That would be a weak decision for two reasons:

1. `breakout_continuation` does not have enough recent local sample in `setup_stats_3d` to support a production exception.
2. Today there is effectively only one name in that subgroup, so changing the rule now would be too close to fitting the day.

## What happens if we remove the active confirmed-pattern penalty

This is the main alternative hypothesis.

Without the active `0.05` operational penalty on `confirmed_pattern`, the deterministic top basket improves sharply and becomes dominated by:

- `FSLR`
- `HPE`
- `FICO`

Their average shrunk edge rises to roughly:

- `+2.93%`

At current sizing, that would imply around:

- `+0.44%` expected portfolio effect

This is meaningful, but still below `+1%`.

More importantly, it directly contradicts the current operational learning layer, which is active because:

- `confirmed_pattern` has deteriorated recently,
- recent `avg_return_3d` is negative,
- and the penalty is there to stop exactly this setup from dominating the prompt.

So removing that penalty today would be an aggressive override, not a conservative improvement.

## Conclusion for today's session

There is no credible conservative path to claim that the system should have captured `+1%` more today.

The evidence instead says:

1. the opportunity set was weak after applying current learning penalties,
2. the best score names were mostly overextended `confirmed_pattern` cases with poor volume confirmation,
3. the only clear momentum continuation case was `BBY`,
4. enabling `BBY` would require a new exception with little local evidence and too much extension tolerance.

In other words:

- today does **not** look like a missed easy edge day,
- today looks like a day where the conservative system was right to remain selective.

## What should change, if anything

### Do not change now

Not recommended:

- remove the `confirmed_pattern` penalty from active mode,
- increase `MAX_POSITION_EXPOSURE`,
- widen `ENTRY_QUALITY_MAX_SMA20_DISTANCE` globally,
- create a production exception for `breakout_continuation`,
- increase `MAX_ORDERS_PER_CYCLE` to force activity.

Those changes would either:

- fight the current learning layer,
- add risk instead of information,
- or overfit to `BBY`.

### Conservative next step

The only defensible next step is a shadow study:

1. create a `breakout_continuation_shadow_exception`,
2. keep it `shadow-only`,
3. require at least:
   - `score >= 15`
   - `volume_zscore_20 >= 1.0`
   - `confirmed bullish patterns >= 1`
   - `close_position_in_range >= 0.80`
4. test it only if:
   - `distance_sma20 <= 0.26`
   - `RSI <= 84`
5. review it walk-forward before any promotion

This is narrow enough to study the `BBY` pattern without weakening the live gate today.

## Final judgment

For `2026-05-28`, the correct answer is:

- **we do not have evidence that a safe production change would have added `+1%`**
- **the best conservative conclusion is to keep the live rules unchanged**
- **the only worthwhile follow-up is a shadow-only study for breakout continuation under strict momentum confirmation**

That is a stronger result than forcing a change:

- it avoids a bad relaxation,
- it respects the active learning penalties,
- and it keeps the system aligned with the actual evidence of the day.
