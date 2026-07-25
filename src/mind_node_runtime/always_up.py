from __future__ import annotations

import functools
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .graph import GraphStore


SERVER_SPACE_ID = "space:l2:mcp:nodes-as-code-server-v0"
STREAM_DECORATOR_SPACE_ID = "space:l2:mcp:stream-logger-decorator-v0"
LATENCY_DECORATOR_SPACE_ID = "space:l2:mcp:flux-latency-decorator-v0"
HEALTH_NODE_ID = "health:l2:mcp:nodes-as-code-server"
ERROR_LOG_NODE_ID = "moment:l2:mcp:server-error-log"

LOG_STREAM_NARRATIVE_ID = "narrative:l2:mcp:stream-recent-logs"
ERROR_STREAM_NARRATIVE_ID = "narrative:l2:mcp:stream-recent-errors"


# --------------------------------------------------------------------------- #
# Flux latency decorator                                                       #
#                                                                             #
# A "flux" decorator that measures the wall-clock latency of the wrapped flow  #
# and appends ONE JSON-line per call to an on-disk log. Deliberately NOT a     #
# per-call graph write: the request path already holds the server's global     #
# dispatch lock, and a graph write per request would add latency and lock      #
# contention to the very flow being measured. The disk append is cheap,        #
# non-blocking, and — critically — can never fail or slow the wrapped call:    #
# every measurement-side error is swallowed. A separate always-on rollup loop  #
# turns this raw stream into a bounded graph Metric/Health (one write per       #
# interval), keeping epistemic honesty (p50/p95/max are *measured*, absence is  #
# *known_absent*) without taxing the hot path.                                 #
# --------------------------------------------------------------------------- #
_LATENCY_WRITE_LOCK = threading.Lock()


def append_jsonl(log_path: str | os.PathLike[str], record: dict[str, Any]) -> None:
    """Append one JSON object as a line to `log_path` (created on demand).

    Serialized across threads by a process-local lock so concurrent request
    threads never interleave a half-written line. Never raises: a logging
    failure must not turn into a request failure."""
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _LATENCY_WRITE_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:  # measurement must never break the measured flow
        print(f"[flux_latency] append failed: {exc}", file=sys.stderr)


def flux_latency(
    log_path: str | os.PathLike[str],
    record_builder: Callable[..., dict[str, Any] | None],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a flow so every invocation is timed and one JSONL record is
    appended to `log_path`.

    `record_builder(args, kwargs, result, exc, duration_ms)` returns the dict to
    log (or None to skip this call, e.g. notifications). The wrapped function's
    return value and raised exceptions are passed through unchanged — this
    decorator is observational only.
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            result: Any = None
            exc: BaseException | None = None
            try:
                result = fn(*args, **kwargs)
                return result
            except BaseException as e:  # noqa: BLE001 (re-raised below, just observed)
                exc = e
                raise
            finally:
                duration_ms = round((time.monotonic() - started) * 1000, 2)
                try:
                    record = record_builder(args, kwargs, result, exc, duration_ms)
                    if record is not None:
                        append_jsonl(log_path, record)
                except Exception as log_exc:  # never fail the wrapped call
                    print(f"[flux_latency] record failed: {log_exc}", file=sys.stderr)

        return wrapper

    return deco


DECORATOR_CODE_NODE_ID = "code:l2:mcp:always-up-decorator:v0"


def ensure_loop_auto_linked(
    graph_store: GraphStore,
    space_id: str,
    fn_name: str,
    module_name: str = "runtime",
    health_node_id: str | None = None,
) -> None:
    """Ensures that space_id and CodeDefinition exist in graph and are explicitly linked

    to the always_up decorator code node and stream logger decorator space loop.

    ``health_node_id`` lets a loop own its OWN health node instead of the shared
    MCP-server health node. When omitted it defaults to the legacy global node so
    existing loops keep byte-for-byte behaviour; passing a per-loop id decouples a
    loop's crash health from the MCP server signal it may itself be watching.
    """
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    code_node_id = f"code:{module_name}:{fn_name.replace('_', '-')}:v0"
    code_node_name = f"CodeDefinition · {fn_name} v0"
    resolved_health_id = health_node_id or HEALTH_NODE_ID

    try:
        graph_store.write(
            """
            MERGE (s:RuntimeNode {id:$space_id})
            ON CREATE SET s.name = $space_name,
                          s.node_type = 'space',
                          s.contractKind = 'self_verifying_loop',
                          s.loopType = 'flux',
                          s.role = 'auto_linked_loop',
                          s.status = 'active',
                          s.created_at = $ts

            MERGE (c:RuntimeNode {id:$code_node_id})
            ON CREATE SET c.name = $code_node_name,
                          c.node_type = 'thing',
                          c.type = 'code',
                          c.language = 'python',
                          c.status = 'active',
                          c.created_at = $ts

            MERGE (h:RuntimeNode {id:$health_id})
            ON CREATE SET h.node_type = 'thing',
                          h.subtype = 'health',
                          h.status = 'active',
                          h.created_at = $ts

            WITH s, c, h
            MATCH (ld:RuntimeNode {id:$stream_decorator_id})
            MATCH (cd:RuntimeNode {id:$decorator_code_id})
            MATCH (nl:RuntimeNode {id:$log_stream_id})
            MATCH (ne:RuntimeNode {id:$error_stream_id})
            MERGE (s)-[:WRAPPED_BY_DECORATOR]->(ld)
            MERGE (s)-[:DEFINED_BY]->(c)
            MERGE (c)-[:USES_DECORATOR]->(cd)
            MERGE (c)-[:GOVERNED_BY_DECORATOR_LOOP]->(ld)
            MERGE (ld)-[:MAINTAINS_LOG_STREAM]->(nl)
            MERGE (ld)-[:MAINTAINS_ERROR_STREAM]->(ne)
            MERGE (s)-[:UPDATES_HEALTH]->(h)
            """,
            {
                "space_id": space_id,
                "space_name": f"Loop · {fn_name} v0",
                "code_node_id": code_node_id,
                "code_node_name": code_node_name,
                "stream_decorator_id": STREAM_DECORATOR_SPACE_ID,
                "decorator_code_id": DECORATOR_CODE_NODE_ID,
                "log_stream_id": LOG_STREAM_NARRATIVE_ID,
                "error_stream_id": ERROR_STREAM_NARRATIVE_ID,
                "health_id": resolved_health_id,
                "ts": timestamp_iso,
            },
        )
    except Exception as exc:
        print(f"[always_up] Warning auto-linking loop {space_id} in graph: {exc}", file=sys.stderr)


VISUAL_DECORATOR_SPACE_ID = "space:l2:mcp:visual-decorator-v0"
VISUAL_DECORATOR_CODE_ID = "code:l2:mcp:visual-decorator:v0"


def record_stream_log(
    graph_store: GraphStore,
    message: str,
    level: str = "info",
    context: str = "server_execution",
    is_visual: bool = False,
) -> dict[str, Any]:
    """Records a normal log entry into narrative:l2:mcp:stream-recent-logs, with optional is_visual flag."""
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "timestamp": timestamp_iso,
        "level": level,
        "context": context,
        "message": message,
        "is_visual": is_visual,
    }

    try:
        rows = graph_store.read(
            "MATCH (n {id:$id}) RETURN n.logs_json, n.log_count",
            {"id": LOG_STREAM_NARRATIVE_ID},
        )
        existing_json = rows[0][0] if rows and rows[0][0] else "[]"
        log_count = (rows[0][1] or 0) if rows else 0
        try:
            logs_list = json.loads(existing_json)
            if not isinstance(logs_list, list):
                logs_list = []
        except Exception:
            logs_list = []

        logs_list.append(log_entry)
        if len(logs_list) > 100:
            logs_list = logs_list[-100:]

        updated_json = json.dumps(logs_list, ensure_ascii=False)
        updated_count = log_count + 1

        graph_store.write(
            """
            MERGE (n:RuntimeNode {id:$id})
            SET n.name = 'Narrative · Recent Execution Logs Stream',
                n.node_type = 'narrative',
                n.type = 'log_stream',
                n.log_count = $count,
                n.last_log = $last_log,
                n.logs_json = $logs_json,
                n.is_visual = $is_visual,
                n.status = 'active',
                n.updated_at = $ts
            """,
            {
                "id": LOG_STREAM_NARRATIVE_ID,
                "count": updated_count,
                "last_log": message,
                "logs_json": updated_json,
                "is_visual": is_visual,
                "ts": timestamp_iso,
            },
        )
    except Exception as exc:
        print(f"[always_up] Failed to record stream log: {exc}", file=sys.stderr)

    return log_entry


def record_server_error(
    graph_store: GraphStore,
    space_id: str = SERVER_SPACE_ID,
    error_exc: Exception | None = None,
    context: str = "server_loop_crash",
    health_node_id: str | None = None,
) -> dict[str, Any]:
    """Sets health status to 0, persists error into narrative:l2:mcp:stream-recent-errors

    and moment:l2:mcp:server-error-log, and creates an incident task node in graph.

    ``health_node_id`` targets a per-loop health node instead of the shared MCP
    server node. When omitted it defaults to the legacy global node so existing
    callers are unchanged; a loop that watches the MCP health node should pass its
    own id so its crashes never falsify the very signal it observes.
    """
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    tb_str = traceback.format_exc() if error_exc else ""
    error_msg = repr(error_exc) if error_exc else "Unknown error"
    resolved_health_id = health_node_id or HEALTH_NODE_ID

    error_entry = {
        "timestamp": timestamp_iso,
        "context": context,
        "error": error_msg,
        "traceback": tb_str,
    }

    # 1. Update health status to 0 on space loop and health node
    try:
        graph_store.write(
            """
            MATCH (s {id:$space_id})
            SET s.health_status = 0, s.last_error_at = $ts
            """,
            {"space_id": space_id, "ts": timestamp_iso},
        )
        graph_store.write(
            """
            MERGE (h:RuntimeNode {id:$health_id})
            ON CREATE SET h.node_type = 'thing', h.subtype = 'health'
            SET h.health_status = 0, h.status = 'degraded', h.last_error = $err, h.updated_at = $ts
            """,
            {"health_id": resolved_health_id, "err": error_msg, "ts": timestamp_iso},
        )
    except Exception as exc:
        print(f"[always_up] Failed to update health_status to 0 in graph: {exc}", file=sys.stderr)

    # 2. Append error entry to narrative:l2:mcp:stream-recent-errors
    try:
        rows = graph_store.read(
            "MATCH (ne {id:$id}) RETURN ne.errors_json, ne.error_count",
            {"id": ERROR_STREAM_NARRATIVE_ID},
        )
        existing_json = rows[0][0] if rows and rows[0][0] else "[]"
        error_count = (rows[0][1] or 0) if rows else 0
        try:
            errors_list = json.loads(existing_json)
            if not isinstance(errors_list, list):
                errors_list = []
        except Exception:
            errors_list = []

        errors_list.append(error_entry)
        if len(errors_list) > 100:
            errors_list = errors_list[-100:]

        updated_json = json.dumps(errors_list, ensure_ascii=False)
        updated_count = error_count + 1

        graph_store.write(
            """
            MERGE (ne:RuntimeNode {id:$id})
            SET ne.name = 'Narrative · Recent Execution Errors Stream',
                ne.node_type = 'narrative',
                ne.type = 'error_stream',
                ne.error_count = $count,
                ne.last_error = $last_err,
                ne.errors_json = $errors_json,
                ne.status = 'active',
                ne.updated_at = $ts
            """,
            {
                "id": ERROR_STREAM_NARRATIVE_ID,
                "count": updated_count,
                "last_err": error_msg,
                "errors_json": updated_json,
                "ts": timestamp_iso,
            },
        )
    except Exception as exc:
        print(f"[always_up] Failed to persist error into narrative {ERROR_STREAM_NARRATIVE_ID}: {exc}", file=sys.stderr)

    # 3. Append to single error log node moment:l2:mcp:server-error-log for backward compatibility
    try:
        rows = graph_store.read(
            "MATCH (m {id:$id}) RETURN m.errors_json, m.error_count",
            {"id": ERROR_LOG_NODE_ID},
        )
        existing_json = rows[0][0] if rows and rows[0][0] else "[]"
        error_count = (rows[0][1] or 0) if rows else 0
        try:
            errors_list = json.loads(existing_json)
            if not isinstance(errors_list, list):
                errors_list = []
        except Exception:
            errors_list = []

        errors_list.append(error_entry)
        if len(errors_list) > 100:
            errors_list = errors_list[-100:]

        graph_store.write(
            """
            MERGE (m:RuntimeNode {id:$id})
            SET m.name = 'Moment · MCP Server Error Log',
                m.node_type = 'moment',
                m.type = 'error_log',
                m.error_count = $count,
                m.last_error = $last_err,
                m.errors_json = $errors_json,
                m.status = 'active',
                m.updated_at = $ts
            """,
            {
                "id": ERROR_LOG_NODE_ID,
                "count": error_count + 1,
                "last_err": error_msg,
                "errors_json": json.dumps(errors_list, ensure_ascii=False),
                "ts": timestamp_iso,
            },
        )
    except Exception as exc:
        print(f"[always_up] Failed to update error log node: {exc}", file=sys.stderr)

    # 4. Create incident task node in graph if server loop crashed
    task_id = f"task:l2:mcp:server-incident-{int(time.time() * 1000)}"
    task_name = f"Incident · Server Loop Failure ({timestamp_iso})"
    task_content = f"Interception d'un crash du serveur MCP (contexte '{context}'). Erreur: {error_msg}"

    try:
        graph_store.write(
            """
            MERGE (t:RuntimeNode {id:$task_id})
            SET t.name = $task_name,
                t.node_type = 'narrative',
                t.type = 'task',
                t.status = 'open',
                t.priority = 'high',
                t.content = $content,
                t.error = $error,
                t.created_at = $ts
            WITH t
            MATCH (s {id:$space_id})
            MATCH (ne {id:$error_narrative_id})
            MERGE (s)-[:HAS_INCIDENT_TASK]->(t)
            MERGE (t)-[:LOGGED_IN]->(ne)
            """,
            {
                "task_id": task_id,
                "task_name": task_name,
                "content": task_content,
                "error": error_msg,
                "ts": timestamp_iso,
                "space_id": space_id,
                "error_narrative_id": ERROR_STREAM_NARRATIVE_ID,
            },
        )
        error_entry["created_task_id"] = task_id
    except Exception as exc:
        print(f"[always_up] Failed to create incident task node in graph: {exc}", file=sys.stderr)

    return error_entry


def always_up(
    fn_or_space_id: Callable[..., Any] | str | None = None,
    *,
    space_id: str | None = None,
    max_restarts: int | None = None,
    backoff_seconds: float = 1.0,
    auto_link: bool = True,
    graph_store: GraphStore | None = None,
    health_node_id: str | None = None,
) -> Callable[..., Any]:
    """Universal Always Up decorator.

    Usage options:
        1. Zero-config decorator:
            @always_up
            def my_worker(): ...

        2. Parametrized decorator:
            @always_up(space_id="space:l2:my-worker-loop-v0")
            def my_worker(): ...

    ``health_node_id`` decouples this loop's crash health from the shared MCP
    server health node. When omitted the legacy global node is used (unchanged
    behaviour). A loop that watches the MCP health node MUST pass its own id so a
    crash of the loop never marks the watched MCP signal as degraded.
    """
    actual_space_id = space_id
    target_fn = None

    if callable(fn_or_space_id):
        target_fn = fn_or_space_id
    elif isinstance(fn_or_space_id, str):
        actual_space_id = fn_or_space_id

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        nonlocal actual_space_id, graph_store
        resolved_space_id = actual_space_id or f"space:l2:{fn.__name__.replace('_', '-')}-loop-v0"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal graph_store
            if graph_store is None:
                try:
                    graph_store = GraphStore(Settings())
                except Exception:
                    graph_store = None

            if auto_link and graph_store:
                ensure_loop_auto_linked(
                    graph_store, resolved_space_id, fn.__name__, health_node_id=health_node_id
                )

            restart_count = 0
            while True:
                if graph_store:
                    try:
                        record_stream_log(
                            graph_store,
                            f"Execution loop attempt #{restart_count + 1} for {fn.__name__}",
                            level="info",
                            context=f"{fn.__name__}_launch",
                        )
                    except Exception:
                        pass

                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    restart_count += 1
                    print(
                        f"[always_up] CRASH in {fn.__name__} (attempt #{restart_count}): {exc}",
                        file=sys.stderr,
                    )
                    if graph_store:
                        record_server_error(
                            graph_store,
                            space_id=resolved_space_id,
                            error_exc=exc,
                            context=f"{fn.__name__}_attempt_{restart_count}",
                            health_node_id=health_node_id,
                        )

                    if max_restarts is not None and restart_count >= max_restarts:
                        print(
                            f"[always_up] Reached max restarts ({max_restarts}) for {fn.__name__}. Exiting loop.",
                            file=sys.stderr,
                        )
                        raise

                    time.sleep(backoff_seconds)

        return wrapper

    if target_fn is not None:
        return decorator(target_fn)
    return decorator


# Backward compatibility and specialization aliases
always_up_server_loop = always_up
stream_logger_decorator = always_up
visual_decorator = always_up
