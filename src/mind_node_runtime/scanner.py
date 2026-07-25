from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import REQUIRED_CHAIN_ROLES


DECORATOR_NAMES = {"always_up", "always_up_server_loop", "stream_logger_decorator"}


def build_blueprint_analysis(
    target: dict[str, Any],
    neighbours: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    neighbours = list(neighbours)
    by_subtype: dict[str, list[dict[str, Any]]] = {}
    for node in neighbours:
        subtype = str(node.get("subtype") or "")
        by_subtype.setdefault(subtype, []).append(node)

    inventory: list[dict[str, Any]] = []
    missing: list[str] = []
    present_roles: list[str] = []
    for role in REQUIRED_CHAIN_ROLES:
        matches = by_subtype.get(role, [])
        if matches:
            status = "present"
            present_roles.append(role)
        else:
            status = "missing"
            missing.append(role)
        inventory.append(
            {
                "role": role,
                "status": status,
                "nodeIds": [item.get("id") for item in matches],
            }
        )

    objective_nodes = by_subtype.get("objective", [])
    objective = {
        "status": "present" if objective_nodes else "missing",
        "nodeIds": [node.get("id") for node in objective_nodes],
        "summary": objective_nodes[0].get("content") if objective_nodes else None,
    }

    first_missing = missing[0] if missing else None
    next_increment = (
        {
            "kind": "complete_next_role",
            "role": first_missing,
            "reason": "first missing role in the canonical loop chain",
        }
        if first_missing
        else {
            "kind": "execute_first_measurement",
            "role": "evaluation_run",
            "reason": "the declared chain is present; produce a real measured result",
        }
    )

    debts = [
        {
            "kind": "missing_loop_role",
            "role": role,
            "severity": "critical" if role in {"objective", "validation", "health"} else "normal",
        }
        for role in missing
    ]

    return {
        "identity": {
            "id": target.get("id"),
            "nodeType": target.get("node_type"),
            "subtype": target.get("subtype"),
            "name": target.get("name"),
            "status": target.get("status"),
        },
        "objective": objective,
        "chainInventory": inventory,
        "causalChain": [
            "objective",
            "behavior",
            "algorithm",
            "code",
            "implementation",
            "validation",
            "observability_algorithm",
            "metric",
            "health",
        ],
        "debtsAndRisks": debts,
        "nextVerticalIncrement": next_increment,
        "honestFinalState": {
            "definedInGraph": True,
            "implemented": "not_measured",
            "executed": False,
            "measured": False,
            "independentlyValidated": False,
            "currentHealth": "not_measured",
            "nextBreakTest": "remove or invalidate one required role and verify detection",
            "presentRoleCount": len(present_roles),
            "requiredRoleCount": len(REQUIRED_CHAIN_ROLES),
        },
    }


# --------------------------------------------------------------------------- #
# AST Scanner for Undecorated Loops & Log-producing Entrypoints               #
# --------------------------------------------------------------------------- #
def _is_decorated_with_always_up(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in DECORATOR_NAMES:
            return True
        if isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name) and dec.func.id in DECORATOR_NAMES:
                return True
            if isinstance(dec.func, ast.Attribute) and dec.func.attr in DECORATOR_NAMES:
                return True
        if isinstance(dec, ast.Attribute) and dec.attr in DECORATOR_NAMES:
            return True
    return False


def _has_execution_loop_or_logging(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, bool]:
    has_loop = False
    has_logs = False
    for child in ast.walk(node):
        if isinstance(child, (ast.While, ast.For)):
            has_loop = True
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id in ("print", "log", "record_stream_log"):
                has_logs = True
            elif isinstance(func, ast.Attribute) and func.attr in ("info", "error", "warning", "debug", "write"):
                has_logs = True
    return has_loop, has_logs


def scan_undecorated_loops(directory_path: Path | str) -> list[dict[str, Any]]:
    """Scans Python files in directory_path for functions or entrypoints containing

    execution loops or logging calls that lack the @always_up decorator.
    """
    directory_path = Path(directory_path)
    if not directory_path.exists():
        return []

    results: list[dict[str, Any]] = []

    files = [directory_path] if directory_path.is_file() else list(directory_path.rglob("*.py"))
    for file_path in files:
        if ".venv" in file_path.parts or "__pycache__" in file_path.parts or "tests" in file_path.parts:
            continue
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                is_decorated = _is_decorated_with_always_up(node)
                has_loop, has_logs = _has_execution_loop_or_logging(node)

                is_candidate = (
                    func_name in ("main", "run", "serve_stdio", "serve_http", "daemon_loop", "worker_loop")
                    or (has_loop and has_logs)
                )

                if is_candidate and not is_decorated:
                    results.append({
                        "file": str(file_path),
                        "line": node.lineno,
                        "function": func_name,
                        "has_loop": has_loop,
                        "has_logs": has_logs,
                        "recommendation": f"Add @always_up to function '{func_name}' at {file_path.name}:{node.lineno}",
                    })

    return results


def audit_repository_loops(root_dir: Path | str, graph_store: Any = None) -> dict[str, Any]:
    """Audits repository Python files for undecorated functions/loops and creates auto-recommendation

    Narrative nodes in FalkorDB linked to target code and recommended decorator nodes.
    """
    candidates = scan_undecorated_loops(root_dir)
    created_recommendations = []

    if graph_store and candidates:
        timestamp_iso = datetime.now(timezone.utc).isoformat()
        try:
            for item in candidates:
                func_name = item["function"]
                rec_id = f"narrative:recommendation:{func_name}:always-up"
                target_code_id = f"code:runtime:{func_name.replace('_', '-')}:v0"
                decorator_code_id = "code:l2:mcp:always-up-decorator:v0"

                rec_name = f"Recommendation · Apply @always_up to {func_name}()"
                rec_content = (
                    f"The function '{func_name}' in {item['file']}:{item['line']} contains an unmonitored "
                    f"execution loop or logging output. Applying @always_up ensures graph-governed resilience, "
                    f"health status regulation, log/error stream persistence, and auto-restart capability."
                )

                graph_store.write(
                    """
                    MERGE (r:RuntimeNode {id:$rec_id})
                    SET r.name = $rec_name,
                        r.node_type = 'narrative',
                        r.type = 'recommendation',
                        r.status = 'proposed',
                        r.priority = 'normal',
                        r.content = $rec_content,
                        r.file = $file,
                        r.line = $line,
                        r.created_at = $ts

                    MERGE (tc:RuntimeNode {id:$target_code_id})
                    ON CREATE SET tc.name = $tc_name,
                                  tc.node_type = 'thing',
                                  tc.type = 'code',
                                  tc.language = 'python',
                                  tc.status = 'active'

                    WITH r, tc
                    MATCH (sw:RuntimeNode {id:'space:l2:antipattern-watch-v0'})
                    MATCH (dc:RuntimeNode {id:$decorator_code_id})

                    MERGE (sw)-[:PROPOSED_RECOMMENDATION]->(r)
                    MERGE (r)-[:RECOMMENDS_DECORATOR]->(dc)
                    MERGE (r)-[:TARGETS_CODE]->(tc)
                    """,
                    {
                        "rec_id": rec_id,
                        "rec_name": rec_name,
                        "rec_content": rec_content,
                        "file": item["file"],
                        "line": item["line"],
                        "target_code_id": target_code_id,
                        "tc_name": f"CodeDefinition · {func_name} v0",
                        "decorator_code_id": decorator_code_id,
                        "ts": timestamp_iso,
                    },
                )
                created_recommendations.append(rec_id)
        except Exception as exc:
            print(f"[scanner] Warning logging recommendations to graph: {exc}", file=sys.stderr)

    return {
        "status": "measured",
        "undecorated_count": len(candidates),
        "candidates": candidates,
        "created_recommendations": created_recommendations,
    }
