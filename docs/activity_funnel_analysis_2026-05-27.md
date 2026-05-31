# Activity Funnel Analysis - 2026-05-27

## Objective

Measure where the system is losing activity frequency without guessing:

- how many strong long candidates exist,
- how many are actually considered by the LLM,
- how many are blocked by filters,
- how many become approved buys,
- how many are really executed.

This analysis is intended to answer why the system currently buys and sells little.

## Measurement notes

Data source:

- `signal_outcomes`
- `trade_recommendations`
- `broker_orders`
- rebuilt through `_rebuild_signal_cohorts(...)`

Important limitation:

- the historical dataset does **not** persist `selected_candidates`, `selection_rank`, or `selection_score` into `features_json`
- therefore, the exact stage `candidate -> selected_candidates` cannot be reconstructed for historical periods
- the first observable post-selection stage is `considered_by_llm`

So the measurable funnel is:

1. `strong_long_total`
2. `considered_by_llm`
3. `hold`
4. `blocked_entry_quality`
5. `blocked_backtest`
6. `approved_buy`
7. `executed_buy`

## Window A: Last 7 Market Days With Evidence

Window:

- 2026-05-07 to 2026-05-22

Observed counts:

- `strong_long_total = 32459`
- `considered_by_llm = 295`
- `candidate_only = 32352`
- `hold = 96`
- `approved_buy = 3`
- `blocked_entry_quality = 7`
- `blocked_backtest = 1`
- `executed_buy = 2`

Rates versus `strong_long_total`:

- `considered_by_llm = 0.91%`
- `hold = 0.30%`
- `approved_buy = 0.01%`
- `blocked_entry_quality = 0.02%`
- `blocked_backtest ~ 0.00%`
- `executed_buy = 0.01%`

## Window B: Recent Full Sample

Window:

- 2026-04-01 to 2026-05-27

Observed counts:

- `strong_long_total = 66969`
- `considered_by_llm = 1127`
- `candidate_only = 66636`
- `hold = 246`
- `approved_buy = 31`
- `blocked_entry_quality = 41`
- `blocked_backtest = 5`
- `executed_buy = 14`

Rates versus `strong_long_total`:

- `considered_by_llm = 1.68%`
- `hold = 0.37%`
- `approved_buy = 0.05%`
- `blocked_entry_quality = 0.06%`
- `blocked_backtest = 0.01%`
- `executed_buy = 0.02%`

## Main conclusion

The biggest bottleneck is not risk filtering.

The dominant bottleneck is:

- **pre-LLM narrowing / candidate prioritization**

Why:

- only `0.91%` of strong long candidates in the last 7 market days were even considered by the LLM
- only `1.68%` in the broader recent sample reached that stage
- `entry_quality` and `backtest_gate` are blocking only a tiny fraction relative to the strong-long universe

This means the system is mostly inactive because:

1. the funnel into the LLM is extremely narrow,
2. the ranking that determines who reaches the prompt matters disproportionately,
3. once a candidate is not surfaced, no later gate can save it.

## Secondary bottlenecks

### 1. Conservative LLM holds

The most repeated hold reasons include:

- open positions not touching stop or take
- candidate has technical quality but no recent statistical edge
- shadow guidance against buying without evidence

This means the LLM layer is conservative, but it is **not** the first bottleneck. It only acts on the tiny set that survives ranking.

### 2. Approved but not executed

Recent full sample:

- `approved_buy = 31`
- `executed_buy = 14`

So even after approval, fewer than half become executed buys.

That is a real bottleneck, but smaller than the selection bottleneck.

Likely contributors include:

- paper-auto-trading settings,
- human approval requirement,
- pending orders,
- session/cycle timing,
- operational constraints.

This is important for operational throughput, but not the main reason the strategy looks inactive.

### 3. Hard filters are not the main throughput problem

Recent full sample:

- `blocked_entry_quality = 41`
- `blocked_backtest = 5`

Against `66969` strong long candidates, that is very small.

Therefore:

- relaxing filters globally would not materially solve activity,
- but it would increase risk.

## What this implies

If the goal is:

- **more activity without lower safety**

then the best levers are:

1. improve ranking before the LLM,
2. widen prompt candidate bandwidth slightly,
3. keep hard filters and risk unchanged,
4. improve execution continuity after approval.

## Link to the recent selector change

The recent change in [trade_decision.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/trade_decision.py) fits this conclusion.

It improves:

- `selection_score`
- `rank_priority_score`

for high-conviction confirmed momentum names.

That is exactly the kind of change that can:

- raise activity a bit,
- improve quality of names seen by the LLM,
- avoid weakening entry safety.

## Why this change will not massively increase activity by itself

Because it does **not** change:

- `ENTRY_QUALITY_MIN_SCORE`
- `entry_quality`
- `backtest_gate`
- `MAX_ORDERS_PER_CYCLE`
- `MAX_DAILY_BUY_ORDERS`
- `ALLOW_POSITION_ADDS`
- exposure limits

So it improves candidate promotion, but does not widen the whole funnel enough to create a large frequency jump alone.

## Most defensible next steps

### 1. Persist selection-stage metadata historically

Persist into `signal_outcomes.features_json`:

- `selection_rank`
- `selection_score`
- `selected_for_llm`

Without this, the exact `candidate -> selected` drop-off cannot be measured retrospectively.

### 2. Increase prompt bandwidth modestly

Conservative option:

- increase `selected_candidates` from `8` to `10` or `12`

This should be shadow-tested first.

Reason:

- the current funnel is so narrow that small improvements upstream can matter more than touching safety filters.

### 3. Audit approved-but-not-executed flow

Measure:

- how many approvals are lost due to manual approval settings,
- timing,
- pending orders,
- market-cycle overlap,
- or operational blocks.

### 4. Keep hard safety rules intact

Do not chase activity by relaxing:

- global score minimum,
- stop/take constraints,
- max risk,
- max exposure,
- shadow-only setup policy.

Those are not the main cause of inactivity and they do protect the system.

## Bottom line

The system is not inactive primarily because it is overblocked by risk filters.

It is inactive primarily because:

- the candidate universe is huge,
- the path into the prompt is very narrow,
- and only a tiny fraction of strong long names ever become real decision candidates.

So the correct way to increase activity safely is:

- better ranking,
- slightly wider prompt intake,
- and cleaner post-approval execution,

not broader relaxation of risk rules.
