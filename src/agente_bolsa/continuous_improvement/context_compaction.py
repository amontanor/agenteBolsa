"""Token-aware context compaction for continuous improvement LLM calls."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


DEFAULT_STRING_LIMIT = 1500
DEFAULT_ERROR_LIMIT = 3000


def estimate_json_tokens(value: Any) -> int:
    text = json.dumps(value, ensure_ascii=True, default=str, separators=(",", ":"))
    return max(1, int(len(text) / 4))


def truncate_string(value: Any, limit: int = DEFAULT_STRING_LIMIT) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}... [truncated {omitted} chars]"


def truncate_list(items: Any, limit: int) -> list[Any]:
    if not isinstance(items, list):
        return []
    return items[: max(0, limit)]


def compact_ci_context_for_llm(
    *,
    context: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    task_payload: dict[str, Any] | None = None,
    deterministic_baseline: dict[str, Any] | None = None,
    safety_rules: dict[str, Any] | None = None,
    target_tokens: int = 40000,
    hard_limit_tokens: int = 55000,
) -> dict[str, Any]:
    return _compact_ci_context(
        context=context,
        evaluation=evaluation,
        event=event,
        task_payload=task_payload,
        deterministic_baseline=deterministic_baseline,
        safety_rules=safety_rules,
        target_tokens=target_tokens,
        hard_limit_tokens=hard_limit_tokens,
        profile="primary",
    )


def compact_ci_context_for_local_fallback(
    *,
    context: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    task_payload: dict[str, Any] | None = None,
    deterministic_baseline: dict[str, Any] | None = None,
    safety_rules: dict[str, Any] | None = None,
    target_tokens: int = 30000,
    hard_limit_tokens: int = 50000,
) -> dict[str, Any]:
    return _compact_ci_context(
        context=context,
        evaluation=evaluation,
        event=event,
        task_payload=task_payload,
        deterministic_baseline=deterministic_baseline,
        safety_rules=safety_rules,
        target_tokens=target_tokens,
        hard_limit_tokens=hard_limit_tokens,
        profile="local",
    )


def compact_messages_for_token_budget(
    messages: list[dict[str, str]],
    *,
    target_tokens: int,
    hard_limit_tokens: int,
    force: bool = False,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    original_tokens = estimate_json_tokens(messages)
    metadata: dict[str, Any] = {
        "compacted": False,
        "original_estimated_tokens": original_tokens,
        "estimated_tokens": original_tokens,
        "target_tokens": target_tokens,
        "hard_limit_tokens": hard_limit_tokens,
        "truncations": [],
    }
    if not force and original_tokens <= target_tokens:
        return messages, metadata

    compacted = _compact_messages(messages, string_limit=1000, list_limit=20, metadata=metadata)
    estimated = estimate_json_tokens(compacted)
    for string_limit, list_limit in ((700, 12), (450, 8), (250, 5), (120, 3)):
        if estimated <= hard_limit_tokens:
            break
        compacted = _compact_messages(messages, string_limit=string_limit, list_limit=list_limit, metadata=metadata)
        estimated = estimate_json_tokens(compacted)

    metadata["compacted"] = compacted != messages
    metadata["estimated_tokens"] = estimated
    return compacted, metadata


def _compact_ci_context(
    *,
    context: dict[str, Any],
    evaluation: dict[str, Any] | None,
    event: dict[str, Any] | None,
    task_payload: dict[str, Any] | None,
    deterministic_baseline: dict[str, Any] | None,
    safety_rules: dict[str, Any] | None,
    target_tokens: int,
    hard_limit_tokens: int,
    profile: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "compacted": True,
        "profile": profile,
        "target_tokens": target_tokens,
        "hard_limit_tokens": hard_limit_tokens,
        "truncations": [],
    }
    local = profile == "local"
    string_limit = 1000 if local else DEFAULT_STRING_LIMIT
    error_limit = 2000 if local else DEFAULT_ERROR_LIMIT
    payload: dict[str, Any] = {
        "real_context": _compact_real_context(
            context,
            latest_events_limit=15 if local else 20,
            proposals_limit=30 if local else 40,
            messages_limit=20 if local else 30,
            string_limit=string_limit,
            error_limit=error_limit,
            metadata=metadata,
        ),
        "deterministic_evaluation": _compact_value(
            evaluation or context.get("evaluation", {}),
            string_limit=string_limit,
            list_limit=20,
            depth=0,
            metadata=metadata,
            path="evaluation",
        ),
    }
    if event is not None:
        payload["event"] = _compact_event(event, string_limit=string_limit, error_limit=error_limit)
    if task_payload is not None:
        payload["task_payload"] = _compact_value(
            task_payload,
            string_limit=string_limit,
            list_limit=20,
            depth=0,
            metadata=metadata,
            path="task_payload",
        )
    if deterministic_baseline is not None:
        payload["deterministic_baseline"] = _compact_value(
            deterministic_baseline,
            string_limit=string_limit,
            list_limit=20,
            depth=0,
            metadata=metadata,
            path="deterministic_baseline",
        )
    if safety_rules is not None:
        payload["safety_rules"] = safety_rules

    _fit_payload(payload, metadata, target_tokens=target_tokens, hard_limit_tokens=hard_limit_tokens)
    payload["_compaction"] = metadata
    final_tokens = estimate_json_tokens(payload)
    if final_tokens > hard_limit_tokens:
        truncations = metadata.get("truncations") or []
        metadata["truncations_omitted"] = max(0, len(truncations) - 10)
        metadata["truncations"] = truncations[:10]
        final_tokens = estimate_json_tokens(payload)
    if final_tokens > hard_limit_tokens:
        metadata["truncations_omitted"] = metadata.get("truncations_omitted", 0) + len(metadata.get("truncations") or [])
        metadata["truncations"] = []
        final_tokens = estimate_json_tokens(payload)
    metadata["estimated_tokens"] = final_tokens
    return payload


def _compact_real_context(
    context: dict[str, Any],
    *,
    latest_events_limit: int,
    proposals_limit: int,
    messages_limit: int,
    string_limit: int,
    error_limit: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    events = context.get("events") or {}
    learning = context.get("learning") or {}
    return {
        "cycle_id": context.get("cycle_id"),
        "collected_at": context.get("collected_at"),
        "runtime": _compact_value(context.get("runtime") or {}, string_limit=string_limit, list_limit=10, depth=0, metadata=metadata, path="runtime"),
        "database": _compact_value(context.get("database") or {}, string_limit=string_limit, list_limit=10, depth=0, metadata=metadata, path="database"),
        "settings": _compact_value(context.get("settings") or {}, string_limit=string_limit, list_limit=10, depth=0, metadata=metadata, path="settings"),
        "events": {
            "latest": [_compact_event(item, string_limit=string_limit, error_limit=error_limit) for item in truncate_list(events.get("latest"), latest_events_limit)],
            "recent_errors": [
                _compact_event(item, string_limit=string_limit, error_limit=error_limit)
                for item in truncate_list(events.get("recent_errors"), 10)
            ],
            "counts": _counts_for(events),
        },
        "reports": _compact_reports(context.get("reports") or {}, string_limit=string_limit, metadata=metadata),
        "learning": {
            "signals": [
                _compact_value(item, string_limit=string_limit, list_limit=8, depth=0, metadata=metadata, path="learning.signals")
                for item in truncate_list(learning.get("signals"), 30)
            ],
            "observations": [
                _compact_value(item, string_limit=string_limit, list_limit=8, depth=0, metadata=metadata, path="learning.observations")
                for item in truncate_list(learning.get("observations"), 30)
            ],
            "policy_candidates": [
                _compact_value(item, string_limit=string_limit, list_limit=8, depth=0, metadata=metadata, path="learning.policy_candidates")
                for item in truncate_list(learning.get("policy_candidates"), 20)
            ],
            "counts": {key: _safe_len(value) for key, value in learning.items()},
        },
        "existing_proposals": [
            _compact_proposal(item, string_limit=string_limit)
            for item in _select_proposals(context.get("existing_proposals") or [], proposals_limit)
        ],
        "initiatives": [
            _compact_initiative(item, string_limit=string_limit) for item in truncate_list(context.get("initiatives"), proposals_limit)
        ],
        "initiative_messages": [
            _compact_message(item, string_limit=string_limit) for item in truncate_list(context.get("initiative_messages"), messages_limit)
        ],
        "hypotheses": [
            _compact_value(item, string_limit=string_limit, list_limit=8, depth=0, metadata=metadata, path="hypotheses")
            for item in truncate_list(context.get("hypotheses"), 20)
        ],
        "memories": [
            _compact_value(item, string_limit=string_limit, list_limit=8, depth=0, metadata=metadata, path="memories")
            for item in truncate_list(context.get("memories"), 20)
        ],
    }


def _fit_payload(payload: dict[str, Any], metadata: dict[str, Any], *, target_tokens: int, hard_limit_tokens: int) -> None:
    estimated = estimate_json_tokens(payload)
    metadata["estimated_tokens_before_fit"] = estimated
    if estimated <= target_tokens:
        metadata["estimated_tokens"] = estimated
        return

    context = payload.get("real_context") or {}
    for key in ("initiative_messages", "existing_proposals", "initiatives", "hypotheses", "memories"):
        if isinstance(context.get(key), list):
            original = len(context[key])
            context[key] = context[key][: max(5, original // 2)]
            _record(metadata, f"real_context.{key}", original, len(context[key]))

    learning = context.get("learning") or {}
    for key in ("signals", "observations", "policy_candidates"):
        if isinstance(learning.get(key), list):
            original = len(learning[key])
            learning[key] = learning[key][:10]
            _record(metadata, f"real_context.learning.{key}", original, len(learning[key]))

    estimated = estimate_json_tokens(payload)
    if estimated > hard_limit_tokens:
        context["reports"] = _summarize_reports_only(context.get("reports") or {})
        events = context.get("events") or {}
        events["latest"] = truncate_list(events.get("latest"), 10)
        events["recent_errors"] = truncate_list(events.get("recent_errors"), 5)
        metadata["hard_limit_fit_applied"] = True

    estimated = estimate_json_tokens(payload)
    for string_limit, list_limit in ((300, 5), (120, 3), (60, 2)):
        if estimated <= target_tokens:
            break
        compacted = _compact_value(
            payload,
            string_limit=string_limit,
            list_limit=list_limit,
            depth=0,
            metadata=metadata,
            path="hard_limit_payload",
        )
        payload.clear()
        payload.update(compacted)
        metadata["aggressive_fit"] = {"string_limit": string_limit, "list_limit": list_limit}
        estimated = estimate_json_tokens(payload)

    metadata["estimated_tokens"] = estimated


def _compact_messages(messages: list[dict[str, str]], *, string_limit: int, list_limit: int, metadata: dict[str, Any]) -> list[dict[str, str]]:
    compacted: list[dict[str, str]] = []
    for index, message in enumerate(messages):
        content = message.get("content", "")
        new_content = content
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            new_content = truncate_string(content, string_limit)
        else:
            parsed = _compact_value(
                parsed,
                string_limit=string_limit,
                list_limit=list_limit,
                depth=0,
                metadata=metadata,
                path=f"messages[{index}]",
            )
            new_content = json.dumps(parsed, ensure_ascii=True, default=str, separators=(",", ":"))
        if new_content != content:
            metadata["compacted"] = True
        compacted.append({**message, "content": new_content})
    return compacted


def _compact_reports(reports: dict[str, Any], *, string_limit: int, metadata: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, report in reports.items():
        if not isinstance(report, dict):
            output[name] = _compact_value(report, string_limit=string_limit, list_limit=5, depth=0, metadata=metadata, path=f"reports.{name}")
            continue
        payload = report.get("payload") if isinstance(report.get("payload"), dict) else report
        output[name] = {
            "available": report.get("available"),
            "path": report.get("path"),
            "summary": _pick_report_fields(payload, string_limit=string_limit, metadata=metadata, path=f"reports.{name}"),
        }
    return output


def _pick_report_fields(payload: dict[str, Any], *, string_limit: int, metadata: dict[str, Any], path: str) -> dict[str, Any]:
    keep = (
        "summary",
        "status",
        "healthy",
        "overall_status",
        "generated_at",
        "created_at",
        "counts",
        "metrics",
        "metrics_snapshot",
    )
    result = {
        key: _compact_value(payload.get(key), string_limit=string_limit, list_limit=8, depth=0, metadata=metadata, path=f"{path}.{key}")
        for key in keep
        if key in payload
    }
    for key in ("issues", "top_issues", "recommendations", "alerts", "warnings", "errors", "key_findings", "proposed_improvements"):
        if key in payload:
            result[key] = _compact_value(
                truncate_list(payload.get(key), 5),
                string_limit=string_limit,
                list_limit=5,
                depth=0,
                metadata=metadata,
                path=f"{path}.{key}",
            )
    return result


def _summarize_reports_only(reports: dict[str, Any]) -> dict[str, Any]:
    summarized: dict[str, Any] = {}
    for name, report in reports.items():
        summary = report.get("summary") if isinstance(report, dict) else report
        if isinstance(summary, dict):
            summarized[name] = {key: summary.get(key) for key in ("summary", "status", "healthy", "overall_status", "issues", "recommendations") if key in summary}
        else:
            summarized[name] = summary
    return summarized


def _compact_event(item: dict[str, Any], *, string_limit: int, error_limit: int) -> dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else item.get("payload_json")
    return {
        "event_type": item.get("event_type"),
        "agent": item.get("agent"),
        "created_at": item.get("created_at"),
        "status": item.get("status"),
        "message": truncate_string(item.get("message") or item.get("reason") or payload, string_limit),
        "error": truncate_string(item.get("error") or _extract_error(payload), error_limit),
    }


def _compact_proposal(item: dict[str, Any], *, string_limit: int) -> dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return {
        "proposal_id": item.get("proposal_id"),
        "status": item.get("status"),
        "priority": item.get("priority"),
        "risk_level": item.get("risk_level") or payload.get("risk_level"),
        "proposal_type": item.get("proposal_type") or payload.get("proposal_type"),
        "target_component": item.get("target_component") or payload.get("target_component"),
        "target_identifier": item.get("target_identifier") or payload.get("target_identifier"),
        "rationale": truncate_string(payload.get("rationale"), string_limit),
        "expected_impact": truncate_string(payload.get("expected_impact"), string_limit),
        "created_at": item.get("created_at"),
    }


def _compact_initiative(item: dict[str, Any], *, string_limit: int) -> dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return {
        "initiative_id": item.get("initiative_id"),
        "initiative_key": item.get("initiative_key"),
        "status": item.get("status"),
        "priority": item.get("priority"),
        "owner_agent": item.get("owner_agent"),
        "last_decision": truncate_string(payload.get("last_decision") or payload.get("decision"), string_limit),
        "next_action": truncate_string(payload.get("next_action") or payload.get("recommended_next_action"), string_limit),
        "updated_at": item.get("updated_at") or item.get("created_at"),
    }


def _compact_message(item: dict[str, Any], *, string_limit: int) -> dict[str, Any]:
    return {
        "initiative_id": item.get("initiative_id"),
        "agent": item.get("agent"),
        "message_type": item.get("message_type"),
        "created_at": item.get("created_at"),
        "content": truncate_string(item.get("content") or item.get("message") or item.get("payload"), string_limit),
    }


def _select_proposals(items: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    priority_statuses = {"PENDING", "FAILED", "READY_TO_APPLY", "REQUIRES_HUMAN_REVIEW", "WAITING_HUMAN_REVIEW"}
    selected = [item for item in items if str(item.get("status") or "").upper() in priority_statuses]
    if len(selected) < limit:
        selected.extend(item for item in items if item not in selected)
    return selected[:limit]


def _compact_value(
    value: Any,
    *,
    string_limit: int,
    list_limit: int,
    depth: int,
    metadata: dict[str, Any],
    path: str,
) -> Any:
    if isinstance(value, str):
        compacted = truncate_string(value, string_limit)
        if compacted != value:
            _record(metadata, path, len(value), string_limit)
        return compacted
    if isinstance(value, dict):
        if depth >= 4:
            _record(metadata, path, len(value), 0)
            return {"summary": f"{len(value)} keys omitted"}
        return {
            str(key): _compact_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                depth=depth + 1,
                metadata=metadata,
                path=f"{path}.{key}",
            )
            for key, item in value.items()
            if not _is_blob_key(str(key))
        }
    if isinstance(value, list):
        original = len(value)
        items = value[:list_limit]
        if original > len(items):
            _record(metadata, path, original, len(items))
        return [
            _compact_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                depth=depth + 1,
                metadata=metadata,
                path=f"{path}[]",
            )
            for item in items
        ]
    return value


def _is_blob_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in {"raw", "raw_response", "html", "csv", "dataframe", "full_report", "payload_blob"} or lowered.endswith("_blob")


def _counts_for(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {key: _safe_len(item) for key, item in value.items()}


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except TypeError:
        return 0


def _extract_error(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("error", "exception", "message"):
            if value.get(key):
                return str(value.get(key))
    return ""


def _record(metadata: dict[str, Any], path: str, original: int, kept: int) -> None:
    truncations = metadata.setdefault("truncations", [])
    if len(truncations) < 80:
        truncations.append({"path": path, "original": original, "kept": kept})
