from __future__ import annotations

import json
import pytest

from mind_node_runtime import (
    CircuitBreakerError,
    RateLimitExceededError,
    circuit_breaker,
    epistemic_provenance,
    idempotency_guard,
    moment_recorder,
    rate_limiter,
    redaction_sanitizer,
)


class MockGraphStore:
    def __init__(self) -> None:
        self.written_queries = []

    def write(self, query: str, params: dict = None) -> list:
        self.written_queries.append((query, params or {}))
        return []

    def read(self, query: str, params: dict = None) -> list:
        return [["Recorded", "active"]]


def test_circuit_breaker():
    call_count = 0

    @circuit_breaker(max_failures=2, reset_timeout=30.0)
    def failing_fn():
        nonlocal call_count
        call_count += 1
        raise ValueError("Failure")

    # Call 1 fails
    with pytest.raises(ValueError):
        failing_fn()
    assert call_count == 1

    # Call 2 fails -> Circuit Breaker switches to OPEN
    with pytest.raises(ValueError):
        failing_fn()
    assert call_count == 2

    # Call 3 fails with CircuitBreakerError immediately without invoking fn
    with pytest.raises(CircuitBreakerError) as exc_info:
        failing_fn()
    assert call_count == 2
    assert "Circuit Breaker for failing_fn is OPEN" in str(exc_info.value)


def test_rate_limiter():
    call_count = 0

    @rate_limiter(rate_limit=2, period=1.0)
    def rate_limited_fn():
        nonlocal call_count
        call_count += 1
        return "ok"

    assert rate_limited_fn() == "ok"
    assert rate_limited_fn() == "ok"

    with pytest.raises(RateLimitExceededError):
        rate_limited_fn()
    assert call_count == 2


def test_idempotency_guard():
    executions = 0

    @idempotency_guard()
    def mutate_data(idempotency_key: str, data: str):
        nonlocal executions
        executions += 1
        return f"processed:{data}"

    r1 = mutate_data(idempotency_key="tx-100", data="hello")
    assert r1 == "processed:hello"
    assert executions == 1

    # Second invocation with same idempotency key returns cached result
    r2 = mutate_data(idempotency_key="tx-100", data="hello")
    assert r2 == "processed:hello"
    assert executions == 1


def test_epistemic_provenance():
    @epistemic_provenance(executor_name="test_executor")
    def compute():
        return {"data": [1, 2, 3]}

    res = compute()
    assert res["information_status"] == "measured"
    assert res["provenance"]["executor"] == "test_executor"
    assert "durationMs" in res["provenance"]


def test_redaction_sanitizer():
    @redaction_sanitizer()
    def get_user_data():
        return {"user": "alice", "auth": "Bearer secret_jwt_token_123"}

    res = get_user_data()
    assert res["auth"] == "Bearer [REDACTED]"
    assert "redactions" in res
    assert "secret_jwt_token_123" in res["redactions"]


def test_moment_recorder():
    mock_store = MockGraphStore()

    @moment_recorder(graph_store=mock_store)
    def run_agent_task():
        return "done"

    res = run_agent_task()
    assert res == "done"
    assert len(mock_store.written_queries) == 1
    assert "MERGE (m:RuntimeNode {id:$id})" in mock_store.written_queries[0][0]
