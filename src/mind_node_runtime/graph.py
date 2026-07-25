from __future__ import annotations

import json
from typing import Any

from falkordb import FalkorDB

from .config import Settings


class GraphStore:
    def __init__(self, settings: Settings) -> None:
        kwargs: dict[str, Any] = {"host": settings.host, "port": settings.port}
        if settings.username:
            kwargs["username"] = settings.username
        if settings.password:
            kwargs["password"] = settings.password
        self.client = FalkorDB(**kwargs)
        self.graph = self.client.select_graph(settings.graph_name)

    @staticmethod
    def rows(result: Any) -> list[list[Any]]:
        return list(getattr(result, "result_set", []) or [])

    def read(self, query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        result = self.graph.ro_query(query, params or {})
        return self.rows(result)

    def write(self, query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        result = self.graph.query(query, params or {})
        return self.rows(result)

    def load_target(self, target_id: str) -> dict[str, Any]:
        rows = self.read(
            """
            MATCH (n {id:$id})
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
            MATCH (target {id:$id})-[r]-(n)
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
            MATCH (p)
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
            MATCH (p {id:$id})
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
            MATCH (p {id:$id})
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
            MATCH (c {id:$id})
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
