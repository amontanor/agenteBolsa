from __future__ import annotations

from types import SimpleNamespace

import pytest

from agente_bolsa.cycle_runner import _crew_provider_failure_retryable


class _ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, response_status: int | str | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if response_status is not None:
            self.response = SimpleNamespace(status_code=response_status)


@pytest.mark.parametrize(
    "error",
    [
        _ProviderError(
            "Task execution failed: Error code: 402 - {'error': {'message': 'Upstream request failed: Insufficient account funds'}}"
        ),
        _ProviderError("Upstream request failed", status_code=402),
        _ProviderError("Upstream request failed", response_status=402),
        _ProviderError("Upstream request failed", response_status="402"),
    ],
)
def test_crew_http_402_is_terminal_before_slow_provider_fallback(error):
    """Local provider doubles reproduce CrewAI's wrapped account-exhaustion error."""

    assert not _crew_provider_failure_retryable(error)


@pytest.mark.parametrize(
    "error",
    [
        _ProviderError("Upstream request failed", status_code=503, response_status=503),
        _ProviderError("Error code: 429 - rate limit reached"),
    ],
)
def test_crew_transient_provider_errors_keep_existing_retry_contract(error):
    assert _crew_provider_failure_retryable(error)


@pytest.mark.parametrize(
    "error",
    [
        _ProviderError("Upstream request failed", status_code=401),
        _ProviderError("Upstream request failed", response_status="401"),
        _ProviderError("Task execution failed: Error code: 401 - api_key_expired"),
        _ProviderError("Upstream request failed: api_key_expired"),
        _ProviderError("Upstream request failed: HTTP 401"),
    ],
)
def test_crew_expired_credentials_do_not_retry_same_request(error):
    assert not _crew_provider_failure_retryable(error)
