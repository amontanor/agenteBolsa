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
# P-L89B-QA: version-policy expectation aligned with the candidate.
# P-L90R10: bound cross-job scheduler concurrency after Raspberry cgroup OOM evidence (0.4.242).
# P-L90R10B: explicit external env carrier for kernel integrity on ARM64 (0.4.243).
# P-L90R10C: non-secret digest carrier for root:root 600 local secret mounts (0.4.244).
# P-L90R10D: Linux scheduler start token and safe legacy-lock recovery (0.4.245).
# P-L84B: prospective agent contract carrier through signal execution gates (0.4.246).
# P-L90R11: default market-data cache follows configured DATA_DIR (0.4.250).
# P-L91: read-only Jetson storage watchdog sampler with JSON telemetry (0.4.251).
# P-L92: digest drops stale missing_report kill-switch reasons when artifact exists (0.4.252).
# P-L93: TTL cache for dashboard hot-path loaders (snapshot/histories/calendar/events) (0.4.253).
# P-L94: intraday scan failure no longer kills the market cycle silently (0.4.254).
# P-L95: capital funnel attachment counters remain fail-open for every carrier label (0.4.255).
# P-L96: canonical selection ledger consumes dataclass recommendations without iterable coercion (0.4.256).
# P-L96R1: close effective identity, fallback lineage, report refs and intraday misfire safety (0.4.258).
# P-L97: explicit operational conclusions for the agent group without claiming predictive value (0.4.260).
# P-L98: align agent catalog identities and expose configured secondary crew agents (0.4.261).
# P-L98R1: never impute legacy empty outputs to succeeded (0.4.262).
# P-L99: connect legacy role crosswalk to productivity and group health consumers (0.4.263).
# P-L100: normalize direct legacy aggregates at the group-review boundary (0.4.264).
# P-L101: preserve producer-agent lineage through signal outcomes and learning (0.4.265).
# P-L102: direction-correct, bounded, agent-scoped learning feedback (0.4.266).
# P-L103: deterministic specialists consume exact learning feedback slices (0.4.267).
# P-L104: structured, non-authoritative specialist evidence packets (0.4.268).
# P-L105: direction-corrected weekly learning scoreboard (0.4.269).
# P-L106: canonical comparable hit-rate metrics (0.4.270).
# P-L107: refresh learning outcomes during empty broker reconciliation (0.4.271).
# P-L108: inspect the exact requested Raspberry candidate image (0.4.272).
# P-L109: separate Jetson mount source and snapshot target host gates (0.4.273).
# P-L110: structured CrewAI participant observability without decision authority (0.4.274).
# P-L111: contextual CrewAI execution evidence without decision authority (0.4.275).
# P-L113: structured advisory group, challenger shadow and paper capital ladder.
# P-L114: canonical latest readers ignore generic reporter rows.
# P-L115: deterministic, read-only validation backlog governance (0.4.278).
# P-L116: unify the Jetson release lineage with advisory improvements.
# P-L117-B1: revalidation preserves authority status and lesson evidence (0.4.282).
# P-L117-D1-R1: producer output carries consumable window observations (0.4.284).
# P-L117-M-R2: make backward guarded-stage rejection explicit (0.4.293).
# P-L117-N2-R1: bounded, validated and fail-open prospective capture (0.4.294).
# P-L118-N2-R2: canonical validation provenance and stable shadow identities (0.4.296).
# P-L118-N2-R3: unresolved receipts stay descriptive until canonical evidence resolves (0.4.297).
# P-L125: port del bucle de mejora P-L120..P-L123 sobre la linea Jetson (0.4.298).
# P-L126: catalogo v4.1 y linea Mejora hoy en UI (0.4.299).
# P-L127: recorte de barras futuras y capture post-cierre SPY (0.4.300).
# P-L128: regla de retire por sangria lenta 10d (0.4.301).
# P-L128fix: orden sync scheduler (0.4.302).
# P-L128fix2: sync evalua de verdad (0.4.303).
# P-L129: resumen Telegram compacto (0.4.304).
# P-L147: crew session headers + P-L149 selection guards (0.4.307).
# P-L152: dashboard Hoy, ceros honestos fuera de sesion, dedup heroe SPY (0.4.308).
# P-L153: autoridad temporal SPY, P/L dia n/d en cerrado, sin punto finde (0.4.309).
# P-L157: migrar el ID retirado de OpenCode Zen en llamadas efectivas (0.4.311).
# P-L157-R1: fallback Go al ID vivo deepseek-v4.1-flash (el ID v4-flash da 403) (0.4.312).
# P-L158-A: temporizador por seccion del dashboard, solo observacion (0.4.313).
# P-L158-A-R1: nivel INFO efectivo para que la linea llegue al log (0.4.314).
# P-L158-A-R2: print directo (el handler de Streamlit filtra INFO) (0.4.315).
# P-L158-B: perfil fino de opening_context/setup/kpis y total_seconds sin doble suma (0.4.316).
# P-L137-R (re-add): trim_to_completed_sessions + cableado de sellos de sesion (0.4.317).
# P-L141: port linea Windows 0.4.234-0.4.246 (funnel dataclass/KeyError, costes calibrados,
# cobertura same-cycle, misfire delays/health, uplift LLM, linkage, flujos EOD, sellos de sesion,
# dashboard Mis inversiones/SPY unico, grace 300/120/120, sesion proveedor Go/Zen, crew fail-open) (0.4.305).
# P-L133-R (re-add): scheduler_skip_summary + signal_outcome_emptiness observacionales fail-open (0.4.318).
# P-L140A-R (re-add): _invested_day_metric + _investments_group, P/L dia sobre invertido (0.4.319).
# P-L140B-R (re-add): _spy_alpha_summary + alpha unico, leaderboard a Config via session_state, baseline sin render (0.4.320).
# P-L155: el lector de recibos EOD de SPY elige por captured_at y comparable sobre
# unavailable, y el productor toma el reloj de captura despues de la descarga.
# Oct07/08: seven-lot integration candidate; reserved after .340/.341 artifacts.
# Oct08: restore scoreboard v3 costs and coverage while preserving exact controls.
# Oct08: restore explicit 300/120/120-second intraday scheduler grace.
# Oct08: LLM uplift fixtures aligned with direction-corrected maturity contract.
# Oct08: combined corrective candidate, separate from isolated reservations.
# Oct08 N2: preserve recovered postmarket/reconciliation identity across sessions (0.4.344).
# Oct08: restore exact order-plan linkage coverage and fail-open health carrier.
# Oct08 P-L80B-DATE: canonical signal-date equality in same-cycle controls (0.4.351).
# Oct08: reuse digest approval inputs without duplicate historical materialization.
# Oct08 N3: selectively revalidate stale data-pipeline blocks from aware current-session evidence (0.4.350).
# Oct08: combined corrective candidate after isolated .349/.350/.351 reservations.
# Oct09 N2: postmarket P/L candidate tolerates unavailable/null metrics (0.4.354).
# Oct09 N2: stream decision-context quality readers with bounded fetchmany (0.4.353).
# Oct09: isolated combined corrective candidate; protected broker review remains separate.
# Oct09 N3: preserve broker enum values and dispatch partial take-profit quantity (0.4.357).
# Oct10 N2: share read-only digest dispatch and avoid main's eager graph in supervisor (0.4.358).
# Oct10 N2: bound comparable-control quality reads to streamed aggregates (0.4.359).
# Oct10 N2: stream origin utility artifact summaries without content_text (0.4.360).
# Oct10: integrated isolated streaming memory candidates for rehearsal (0.4.361).
# Oct11: deterministic QA fixture dates and integrated release validation (0.4.362).
# Oct11: bounded approval artifact reader; preserves digest contract.
# Oct11: stream research cycles and release reconstructed run states.
# Oct12: human-gated proportional paper capital; score and adds remain separate.
# Oct13: compact historical learning carriers and fail-fast CI HTTP402; policy inactive.
__version__ = "0.4.373"
