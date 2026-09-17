"""Agente Bolsa package."""

__all__ = ["__version__"]

# Semantic versioning (major.minor.patch).
# Bump this on every functional, UI, behavior, or shipped product change.
# P-L50B: immutable lineage/input propagation into the P-L44 shadow (0.4.188).
# P-L52B-W shadow contract for canonical EOD accounting (0.4.190).
# P-L53B-W shadow candidate: canonical selection ledger by cycle.
# QA correction: empty read-only DATA_DIR returns collecting without opening a write DB.
# P-L53BR1: integrated selection ledger over the P-L52BR1 rehearsal (0.4.191).
# P-L48BR1 QA rehearsal: identity fallback and digest conflict fixes (0.4.185).
# P-L43C-W shadow carrier: causal time-stop authority in the reserved 0.4.192 slot.
# P-L43C-R1: broker order durability precedes shadow authority telemetry (0.4.192).
# P-L57A: null-safe postmarket scoreboard continuity (0.4.193).
# P-L58R1: combined measurement-safety rehearsal (0.4.193).
# P-L54B-W: fail-open capital deployment funnel shadow (0.4.194).
# P-L46BR4: calendar-safe portfolio chart filter (0.4.195).
# P-L59C-R2: normalize_llm_selected moved to decision_context, economic parity (0.4.196).
# P-L59F-I: decision_rows v2 in canonical selection ledger, candidate summary, bounded 600 (0.4.197).
# P-L59F-I-R1: identity-key 4-tuple, missing-ID in decision_rows, hash-after-attachments, any-aggregation, client_order_id, denominador pre-truncation.
# P-L63: April equity baseline shared by account header and portfolio chart (0.4.198).
# P-L65A: daily System versus SP500 contract characterization (0.4.199).
# P-L65B: coherent daily System versus SP500 UI contract (0.4.200).
# P-L66: optional Telegram daily summary (0.4.201).
# P-L68: explicit benchmark basis, correct daily freshness and provisional chart.
# P-L71: EOD benchmark authority and temporal-consistent consumer overlay.
# P-L70: Telegram daily summary UX and coverage contract (0.4.203).
# P-L72: opening-to-opening account and SPY performance, shared by UI and Telegram (0.4.206).
# P-L73: position-level total and current-day P/L from the same Alpaca snapshot.
# P-L74: deterministic SPY opening authority and explicit session interval UX (0.4.208).
# P-L76R1: isolate P-L54 conflict reads from broker-order status (0.4.210).
# P-L77B1: fail-closed adaptive override authority and session expiry (0.4.211).
# P-L78B: DeepSeek V4 Flash as the runtime LLM default and effective identity carrier (0.4.212).
# P-L78C: genuinely read-only schedule-status contract (0.4.213).
# P-L79: Arrow-safe text boundary for the Streamlit configuration table (0.4.214).
# P-L80B: prospective exact same-cycle decision/capacity carrier (0.4.215).
# P-L80H2: single-call OpenCode Go / DeepSeek V4 Flash health probe (0.4.216).
# P-L81: canonical previous-close daily equity metric and connected opening chart (0.4.217).
# P-L82: group-level SPY opening authority and visible omitted-session reasons (0.4.218).
# P-L82R: do not connect omitted XNYS intervals; require aligned current comparison (0.4.219).
# P-L83D: normalize Alpaca daily buckets to XNYS sessions and preserve current equity (0.4.220).
# P-L85: OpenCode Zen Free primary with one-shot OpenCode Go fallback (0.4.221).
# P-L86R: hidden /kindle page inside the existing Streamlit web task (0.4.222).
# P-L86K: raw HTML /kindle route for non-JavaScript Kindle browsers (0.4.223).
# P-L87: dashboard position-day reconciliation and sales since XNYS open (0.4.224).
# P-L88: coherent opening-to-now System/SPY UI and portfolio-point percentages (0.4.225).
# P-L89B: exact capital funnel and EOD observational carriers (0.4.226).
# P-L89B-QA: version-policy expectation aligned with the candidate.`r`n# P-L120: deterministic bridge-contract provider unblocks measured CODE_CHANGE proposals (0.4.227).
__version__ = "0.4.227"

