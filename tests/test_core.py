import json
from mind_node_runtime.contracts import REQUIRED_CHAIN_ROLES, validate_output
from mind_node_runtime.hashing import canonical_json, stable_id
from mind_node_runtime.scanner import build_blueprint_analysis


def test_stable_id_is_deterministic() -> None:
    assert stable_id("intent", "a", {"b": 1}) == stable_id("intent", "a", {"b": 1})
    assert stable_id("intent", "a", {"b": 1}) != stable_id("intent", "a", {"b": 2})


def test_canonical_json_orders_keys() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_minimal_blueprint_is_not_overclaimed() -> None:
    target = {
        "id": "space:test",
        "node_type": "space",
        "subtype": "ontology_module",
        "name": "Test",
        "status": "planned",
    }
    neighbours = [
        {
            "id": "objective:test",
            "node_type": "narrative",
            "subtype": "objective",
            "content": "Protect an objective",
        }
    ]
    result = build_blueprint_analysis(target, neighbours)
    inventory = {item["role"]: item["status"] for item in result["chainInventory"]}
    assert inventory["objective"] == "present"
    assert inventory["health"] == "missing"
    assert result["honestFinalState"]["implemented"] == "not_measured"
    assert result["honestFinalState"]["currentHealth"] == "not_measured"
    assert len(result["chainInventory"]) == len(REQUIRED_CHAIN_ROLES)
    assert validate_output(result) == []

from mind_node_runtime.contracts import validate_against_schema
from mind_node_runtime.input_utils import parse_json_input


def test_generic_schema_validator() -> None:
    schema = {
        "type": "object",
        "required": ["name", "mode"],
        "properties": {
            "name": {"type": "string"},
            "mode": {"enum": ["audit", "complete"]},
        },
    }
    assert validate_against_schema({"name": "x", "mode": "audit"}, schema) == []
    errors = validate_against_schema({"name": 42, "mode": "wrong"}, schema)
    assert len(errors) == 2


def test_parse_json_input_requires_object() -> None:
    assert parse_json_input('{"x": 1}', None) == {"x": 1}

from mind_node_runtime.seed import default_objective_id


def test_default_objective_id_from_space_id() -> None:
    assert (
        default_objective_id("space:mind-meta:evaluation-run-v0")
        == "objective:mind-meta:evaluation-run-v0:primary"
    )

from pathlib import Path

from mind_node_runtime.materialize import (
    canonical_payload,
    relative_path_for,
    resolve_program,
    sync_all,
)


class FakeCodeStore:
    def __init__(self, nodes: list[dict[str, object]]) -> None:
        self.nodes = {str(node["id"]): node for node in nodes}

    def list_code_nodes(self) -> list[dict[str, object]]:
        return list(self.nodes.values())

    def load_code_node(self, program_id: str) -> dict[str, object]:
        return self.nodes[program_id]


def _python_node(source: str = "print('hello')\n") -> dict[str, object]:
    return {
        "id": "code:test:hello:v0",
        "node_type": "thing",
        "subtype": "code",
        "name": "Hello",
        "version": "0.1.0",
        "language": "python",
        "artifact_kind": "python_script",
        "authority_mode": "graph_source",
        "source": source,
        "source_hash": None,
        "executor_type": "python_script",
        "content": None,
        "structured_definition_json": None,
        "status": "active",
    }


def test_code_materialization_path_and_exact_source(tmp_path: Path) -> None:
    node = _python_node()
    content, kind = canonical_payload(node)
    assert content == "print('hello')\n"
    assert kind == "source"
    assert relative_path_for(node, kind).as_posix() == "code/test/hello/v0.py"

    result = sync_all(FakeCodeStore([node]), tmp_path)
    assert result["created"] == 1
    assert (tmp_path / "code/test/hello/v0.py").read_text(encoding="utf-8") == content
    assert (tmp_path / ".mind-code-manifest.json").exists()


def test_resolve_uses_local_only_when_hash_is_fresh(tmp_path: Path) -> None:
    node = _python_node("print('v1')\n")
    store = FakeCodeStore([node])

    first = resolve_program(store, str(node["id"]), tmp_path)
    assert first["resolution"] == "graph_live"

    second = resolve_program(store, str(node["id"]), tmp_path)
    assert second["resolution"] == "local_fresh"

    store.nodes[str(node["id"])] = _python_node("print('v2')\n")
    third = resolve_program(store, str(node["id"]), tmp_path)
    assert third["resolution"] == "graph_live"
    assert Path(str(third["path"])).read_text(encoding="utf-8") == "print('v2')\n"


def test_structured_code_node_materializes_as_json(tmp_path: Path) -> None:
    node = _python_node("")
    node["language"] = "expression_ir"
    node["artifact_kind"] = "evaluation_procedure"
    node["authority_mode"] = "graph_structured_definition"
    node["structured_definition_json"] = '{"kind":"literal","value":true}'

    result = sync_all(FakeCodeStore([node]), tmp_path)
    assert result["metadata_only"] == 1
    path = tmp_path / "code/test/hello/v0.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["structuredDefinition"]["kind"] == "literal"
