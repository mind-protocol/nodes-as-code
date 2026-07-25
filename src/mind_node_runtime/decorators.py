from __future__ import annotations

import functools
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from .config import Settings
from .graph import GraphStore


CIRCUIT_BREAKER_SPACE_ID = "space:l2:mcp:circuit-breaker-decorator-v0"
RATE_LIMITER_SPACE_ID = "space:l2:mcp:rate-limiter-decorator-v0"
IDEMPOTENCY_SPACE_ID = "space:l2:mcp:idempotency-decorator-v0"
EPISTEMIC_SPACE_ID = "space:l2:mcp:epistemic-provenance-decorator-v0"
REDACTION_SPACE_ID = "space:l2:mcp:redaction-sanitizer-decorator-v0"
MOMENT_RECORDER_SPACE_ID = "space:l2:mcp:moment-recorder-decorator-v0"


# --------------------------------------------------------------------------- #
# 1. Circuit Breaker Decorator                                                #
# --------------------------------------------------------------------------- #
class CircuitBreakerError(RuntimeError):
    """Raised when call is blocked because Circuit Breaker is OPEN."""


def circuit_breaker(
    max_failures: int = 5,
    reset_timeout: float = 30.0,
    space_id: str = CIRCUIT_BREAKER_SPACE_ID,
    graph_store: GraphStore | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Circuit Breaker decorator protecting downstream systems from repeated failure cascades."""
    state = "CLOSED"
    failure_count = 0
    last_failure_time = 0.0

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal state, failure_count, last_failure_time
            now = time.monotonic()

            if state == "OPEN":
                if now - last_failure_time > reset_timeout:
                    state = "HALF_OPEN"
                else:
                    raise CircuitBreakerError(
                        f"Circuit Breaker for {fn.__name__} is OPEN (failures: {failure_count}). Call rejected."
                    )

            try:
                result = fn(*args, **kwargs)
                if state == "HALF_OPEN":
                    state = "CLOSED"
                    failure_count = 0
                return result
            except Exception as exc:
                failure_count += 1
                last_failure_time = now
                if failure_count >= max_failures:
                    state = "OPEN"
                    print(f"[circuit_breaker] State for {fn.__name__} switched to OPEN after {failure_count} failures.", file=sys.stderr)
                raise exc

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# 2. Rate Limiter Decorator                                                  #
# --------------------------------------------------------------------------- #
class RateLimitExceededError(RuntimeError):
    """Raised when call rate exceeds allowed limit."""


def rate_limiter(
    rate_limit: int = 10,
    period: float = 1.0,
    space_id: str = RATE_LIMITER_SPACE_ID,
    graph_store: GraphStore | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Rate Limiter decorator enforcing maximum calls per period."""
    call_timestamps: list[float] = []

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            now = time.monotonic()
            # Clear expired timestamps
            cutoff = now - period
            while call_timestamps and call_timestamps[0] < cutoff:
                call_timestamps.pop(0)

            if len(call_timestamps) >= rate_limit:
                raise RateLimitExceededError(
                    f"Rate limit of {rate_limit} calls per {period}s exceeded for {fn.__name__}."
                )

            call_timestamps.append(now)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# 3. Idempotency Guard Decorator                                             #
# --------------------------------------------------------------------------- #
def idempotency_guard(
    key_builder: Callable[..., str] | None = None,
    space_id: str = IDEMPOTENCY_SPACE_ID,
    graph_store: GraphStore | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Idempotency guard decorator ensuring side effects run once per idempotency key."""
    seen_keys: dict[str, Any] = {}

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build key from kwargs or key_builder
            key = kwargs.get("idempotency_key")
            if not key and key_builder:
                key = key_builder(*args, **kwargs)
            if not key:
                key = f"{fn.__name__}:{hash(str(args) + str(sorted(kwargs.items())))}"

            if key in seen_keys:
                print(f"[idempotency_guard] Returning cached result for key {key!r}", file=sys.stderr)
                return seen_keys[key]

            result = fn(*args, **kwargs)
            seen_keys[key] = result
            return result

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# 4. Epistemic Provenance Decorator                                          #
# --------------------------------------------------------------------------- #
def epistemic_provenance(
    executor_name: str = "graph_authorized_executor",
    space_id: str = EPISTEMIC_SPACE_ID,
    graph_store: GraphStore | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Ensures function result dictionary contains explicit epistemic status and provenance metadata."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                res = fn(*args, **kwargs)
                duration_ms = round((time.monotonic() - started) * 1000, 2)
                if isinstance(res, dict):
                    res.setdefault("information_status", "measured")
                    prov = res.setdefault("provenance", {})
                    if isinstance(prov, dict):
                        prov.update({
                            "executor": executor_name,
                            "durationMs": duration_ms,
                            "timestamp": int(time.time() * 1000),
                        })
                return res
            except Exception as exc:
                duration_ms = round((time.monotonic() - started) * 1000, 2)
                return {
                    "information_status": "measurement_failed",
                    "error": repr(exc),
                    "provenance": {
                        "executor": executor_name,
                        "durationMs": duration_ms,
                        "timestamp": int(time.time() * 1000),
                    },
                }

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# 5. Redaction Sanitizer Decorator                                           #
# --------------------------------------------------------------------------- #
SENSITIVE_PATTERNS = [
    re.compile(r"Bearer\s+([A-Za-z0-9_\-\.\~]+)", re.IGNORECASE),
    re.compile(r"password=([^\s&]+)", re.IGNORECASE),
    re.compile(r"api_key=([^\s&]+)", re.IGNORECASE),
]


def sanitize_text(text: str) -> tuple[str, list[str]]:
    redactions = []
    sanitized = text
    for pattern in SENSITIVE_PATTERNS:
        matches = pattern.findall(sanitized)
        for match in matches:
            redactions.append(match)
            sanitized = sanitized.replace(match, "[REDACTED]")
    return sanitized, redactions


def redaction_sanitizer(
    space_id: str = REDACTION_SPACE_ID,
    graph_store: GraphStore | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Sanitizes text/dictionary outputs to redact sensitive credentials before persistence."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            res = fn(*args, **kwargs)
            if isinstance(res, str):
                sanitized, _ = sanitize_text(res)
                return sanitized
            if isinstance(res, dict):
                res_str = json.dumps(res)
                sanitized_str, redactions = sanitize_text(res_str)
                if redactions:
                    try:
                        clean_dict = json.loads(sanitized_str)
                        clean_dict["redactions"] = redactions
                        return clean_dict
                    except Exception:
                        pass
            return res

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# 6. Moment Recorder Decorator                                               #
# --------------------------------------------------------------------------- #
def moment_recorder(
    space_id: str = MOMENT_RECORDER_SPACE_ID,
    graph_store: GraphStore | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Records function execution as a Moment node in FalkorDB."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal graph_store
            if graph_store is None:
                try:
                    graph_store = GraphStore(Settings())
                except Exception:
                    graph_store = None

            res = fn(*args, **kwargs)
            if graph_store:
                ts_ms = int(time.time() * 1000)
                moment_id = f"moment:l2:execution-{fn.__name__}-{ts_ms}"
                timestamp_iso = datetime.now(timezone.utc).isoformat()
                try:
                    graph_store.write(
                        """
                        MERGE (m:RuntimeNode {id:$id})
                        SET m.name = $name,
                            m.node_type = 'moment',
                            m.type = 'execution_event',
                            m.function_name = $fn_name,
                            m.created_at = $ts,
                            m.status = 'recorded'
                        WITH m
                        MATCH (s:RuntimeNode {id:$space_id})
                        MERGE (s)-[:PRODUCED_MOMENT]->(m)
                        """,
                        {
                            "id": moment_id,
                            "name": f"Moment · Execution ({fn.__name__})",
                            "fn_name": fn.__name__,
                            "ts": timestamp_iso,
                            "space_id": space_id,
                        },
                    )
                except Exception as exc:
                    print(f"[moment_recorder] Failed to record moment node: {exc}", file=sys.stderr)

            return res

        return wrapper

    return decorator
