from __future__ import annotations

import json
import threading
import time
from typing import Any

from falkordb import FalkorDB

from .config import Settings

try:  # transient failures worth reconnecting on; falkordb speaks the redis protocol
    from redis.exceptions import ConnectionError as _RedisConnectionError
    from redis.exceptions import TimeoutError as _RedisTimeoutError

    _TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
        _RedisConnectionError,
        _RedisTimeoutError,
        ConnectionError,
        TimeoutError,
        OSError,
    )
except Exception:  # pragma: no cover - redis ships with falkordb, but stay safe
    _TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError)


class GraphStore:
    max_retries: int = 3
    base_backoff_seconds: float = 0.2

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Per-thread connection. A single FalkorDB client/connection is NOT safe
        # for concurrent use — two threads sharing one connection interleave the
        # redis protocol stream and corrupt responses. Historically the MCP server
        # guarded this shared connection with a global lock, which serialized ALL
        # requests and made a slow graph write block every other request behind it.
        # Giving each thread its OWN connection removes the shared mutable state,
        # so the lock is no longer needed and independent requests run concurrently
        # (the DB server still serializes each command atomically). Single-threaded
        # callers (daemon/worker/scheduler) see exactly one connection, as before.
        self._local = threading.local()

    def _connect(self) -> None:
        kwargs: dict[str, Any] = {"host": self.settings.host, "port": self.settings.port}
        if self.settings.username:
            kwargs["username"] = self.settings.username
        if self.settings.password:
            kwargs["password"] = self.settings.password
        client = FalkorDB(**kwargs)
        self._local.client = client
        self._local.graph = client.select_graph(self.settings.graph_name)

    @property
    def client(self) -> Any:
        if getattr(self._local, "client", None) is None:
            self._connect()
        return self._local.client

    @property
    def graph(self) -> Any:
        if getattr(self._local, "graph", None) is None:
            self._connect()
        return self._local.graph

    def _run(self, operation: Any) -> Any:
        # Retry transient FalkorDB/redis failures, reconnecting between attempts,
        # so a database blip degrades to a retry instead of killing the daemon.
        # Non-transient errors (bad Cypher, missing data) are re-raised immediately.
        # Writes are retried too: on a dropped connection the query usually never
        # reached the server, so semantics are at-least-once (MERGE/stable ids stay
        # idempotent; CREATE-with-uuid may leave an orphan run/result, never corruption).
        last_error: BaseException | None = None
        for attempt in range(self.max_retries):
            try:
                return operation()
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                try:
                    self._connect()
                except _TRANSIENT_ERRORS:
                    pass
                time.sleep(self.base_backoff_seconds * (2 ** attempt))
        assert last_error is not None
        raise last_error

    @staticmethod
    def rows(result: Any) -> list[list[Any]]:
        return list(getattr(result, "result_set", []) or [])

    def read(self, query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        result = self._run(lambda: self.graph.ro_query(query, params or {}))
        return self.rows(result)

    def write(self, query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        result = self._run(lambda: self.graph.query(query, params or {}))
        return self.rows(result)

    def load_target(self, target_id: str) -> dict[str, Any]:
        rows = self.read(
            """
            MATCH (n:RuntimeNode {id:$id})
            RETURN n.id, n.node_type, n.subtype, n.name, n.status, n.content
            """,
            {"id": target_id},
        )
        if not rows:
            raise KeyError(f"target not found: {target_id}")
        row = rows[0]
        return {
            "id": row[0],
            "node_type": row[1],
            "subtype": row[2],
            "name": row[3],
            "status": row[4],
            "content": row[5],
        }

    def load_neighbours(self, target_id: str) -> list[dict[str, Any]]:
        rows = self.read(
            """
            MATCH (target:RuntimeNode {id:$id})-[r]-(n)
            RETURN n.id, n.node_type, n.subtype, n.name, n.status, n.content, type(r)
            """,
            {"id": target_id},
        )
        return [
            {
                "id": row[0],
                "node_type": row[1],
                "subtype": row[2],
                "name": row[3],
                "status": row[4],
                "content": row[5],
                "relation": row[6],
            }
            for row in rows
        ]


    @staticmethod
    def _code_node_from_row(row: list[Any]) -> dict[str, Any]:
        return {
            "id": row[0],
            "node_type": row[1],
            "subtype": row[2],
            "name": row[3],
            "version": row[4],
            "language": row[5],
            "artifact_kind": row[6],
            "authority_mode": row[7],
            "source": row[8],
            "source_hash": row[9],
            "executor_type": row[10],
            "content": row[11],
            "structured_definition_json": row[12],
            "status": row[13],
        }

    def list_code_nodes(self) -> list[dict[str, Any]]:
        rows = self.read(
            """
            MATCH (p:RuntimeNode)
            WHERE p.node_type='thing' AND coalesce(p.subtype, p.type)='code'
            RETURN p.id, p.node_type, coalesce(p.subtype, p.type), p.name, p.version, p.language,
                   coalesce(p.artifact_kind, p.artifactKind),
                   coalesce(p.authority_mode, p.authorityMode),
                   p.source, coalesce(p.source_hash, p.sourceHash),
                   coalesce(p.executor_type, p.executorType),
                   p.content,
                   coalesce(p.structured_definition_json, p.structuredDefinitionJson),
                   p.status
            ORDER BY p.id
            """
        )
        return [self._code_node_from_row(row) for row in rows]

    def load_code_node(self, program_id: str) -> dict[str, Any]:
        rows = self.read(
            """
            MATCH (p:RuntimeNode {id:$id})
            WHERE p.node_type='thing' AND coalesce(p.subtype, p.type)='code'
            RETURN p.id, p.node_type, coalesce(p.subtype, p.type), p.name, p.version, p.language,
                   coalesce(p.artifact_kind, p.artifactKind),
                   coalesce(p.authority_mode, p.authorityMode),
                   p.source, coalesce(p.source_hash, p.sourceHash),
                   coalesce(p.executor_type, p.executorType),
                   p.content,
                   coalesce(p.structured_definition_json, p.structuredDefinitionJson),
                   p.status
            """,
            {"id": program_id},
        )
        if not rows:
            raise KeyError(f"code node not found: {program_id}")
        return self._code_node_from_row(rows[0])

    def load_program(self, program_id: str) -> dict[str, Any]:
        rows = self.read(
            """
            MATCH (p:RuntimeNode {id:$id})
            RETURN p.id, p.version, p.source, p.source_hash, p.executor_type,
                   p.artifact_kind, p.fallback_executor, p.entrypoint,
                   p.authority_mode, p.status
            """,
            {"id": program_id},
        )
        if not rows:
            raise KeyError(f"program not found: {program_id}")
        row = rows[0]
        return {
            "id": row[0],
            "version": row[1],
            "source": row[2],
            "source_hash": row[3],
            "executor_type": row[4],
            "artifact_kind": row[5],
            "fallback_executor": row[6],
            "entrypoint": row[7],
            "authority_mode": row[8],
            "status": row[9],
        }

    def load_contract(self, contract_id: str) -> dict[str, Any]:
        rows = self.read(
            """
            MATCH (c:RuntimeNode {id:$id})
            RETURN c.id, c.version, c.input_schema_json, c.output_schema_json,
                   c.result_type
            """,
            {"id": contract_id},
        )
        if not rows:
            raise KeyError(f"contract not found: {contract_id}")
        row = rows[0]
        return {
            "id": row[0],
            "version": row[1],
            "input_schema": json.loads(row[2]),
            "output_schema": json.loads(row[3]),
            "result_type": row[4] or "generic_evaluation_result",
        }
