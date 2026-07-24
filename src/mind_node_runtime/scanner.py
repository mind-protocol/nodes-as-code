from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import REQUIRED_CHAIN_ROLES


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
