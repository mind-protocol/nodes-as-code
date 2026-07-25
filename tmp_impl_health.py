
ifrom mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore
from collections import defaultdict
import json
store = GraphStore(Settings())

project_id = "project:mind-brain:evaluation-v0"
parent_space = "space:mind-projects:brain-l1-validation-health-v0"

dimensions = [
    {
        "slug": "contracts-orchestration",
        "name": "Contracts & Orchestration",
        "criteria": [
            "schema_validity", "interface_compatibility", "execution_order",
            "cycle_absence", "tick_correlation", "liveness"
        ],
        "critical": True,
    },
    {
        "slug": "perception-state",
        "name": "Perception & State",
        "criteria": [
            "percept_grounding", "provenance_coverage", "unknown_semantics",
            "metabolic_state_quality", "affective_state_grounding"
        ],
        "critical": True,
    },
    {
        "slug": "physics-context",
        "name": "Physics & Context",
        "criteria": [
            "energy_conservation", "bounded_traversal", "retrieval_precision",
            "retrieval_recall", "contradiction_recall", "hub_resistance", "latency"
        ],
        "critical": True,
    },
    {
        "slug": "workspace-subentities",
        "name": "Workspace & Subentities",
        "criteria": [
            "activation_grounding", "false_awakening_rate", "dissent_preservation",
            "workspace_budget", "capture_rate", "task_continuity"
        ],
        "critical": True,
    },
    {
        "slug": "cognition-response",
        "name": "Cognition & Response",
        "criteria": [
            "dispatch_accuracy", "task_success", "unsupported_claim_rate",
            "abstention_quality", "exactly_once", "latency", "model_cost"
        ],
        "critical": True,
    },
    {
        "slug": "end-to-end-acceptance",
        "name": "End-to-End Acceptance",
        "criteria": [
            "golden_dataset", "conversation_replay", "ablation_gain",
            "shadow_mode", "unauthorized_effects", "duplicate_responses",
            "regression_free", "baseline_comparison"
        ],
        "critical": True,
    },
]

nodes = [
    {
        "id": parent_space,
        "node_type": "space",
        "subtype": "self_verifying_loop",
        "name": "Project Health Â· Brain L1 Validation v0",
        "status": "unknown",
        "content": (
            "Loop parente de santÃ© du projet Brain L1. AgrÃ¨ge les dimensions critiques "
            "sans moyenne masquante. UNKNOWN si une mesure critique manque ou Ã©choue; "
            "UNHEALTHY si une dimension critique Ã©choue; DEGRADED en cas d'avertissement "
            "ou rÃ©gression non critique; HEALTHY uniquement si toutes les dimensions "
            "critiques sont mesurÃ©es et saines et si l'acceptation end-to-end est saine."
        ),
    },
    {
        "id": "health:mind-projects:brain-l1-validation",
        "node_type": "narrative",
        "subtype": "health",
        "name": "Health Â· Brain L1 Validation Project",
        "status": "unknown",
        "content": "RÃ©sumÃ© global de santÃ© du projet. Ne doit jamais Ãªtre healthy par dÃ©faut.",
    },
    {
        "id": "metric:mind-projects:brain-l1-validation-health",
        "node_type": "thing",
        "subtype": "metric",
        "name": "Metric Â· Brain L1 Validation Global Health",
        "status": "unknown",
        "content": json.dumps({
            "aggregation": "critical_worst_status",
            "statuses": ["unknown", "unhealthy", "degraded", "healthy"],
            "healthy_gate": "all critical child dimensions measured healthy and e2e healthy",
            "separate_fields": ["progress", "health", "readiness"],
        }, ensure_ascii=False),
    },
    {
        "id": "observer:mind-projects:brain-l1-validation-health",
        "node_type": "thing",
        "subtype": "observer",
        "name": "Observer Â· Brain L1 Validation Global Health",
        "status": "unknown",
        "content": "AgrÃ¨ge les health enfants, dÃ©tecte mesures absentes/stale et bloque le healthy artificiel.",
    },
    {
        "id": "objective:mind-projects:brain-l1-validation-health-honest",
        "node_type": "narrative",
        "subtype": "objective",
        "name": "Donner une vision honnÃªte et actionnable de la santÃ© du projet Brain L1",
        "status": "active",
        "content": "SÃ©parer progression, santÃ© et readiness; prÃ©server les blockers et mesures manquantes.",
    },
    {
        "id": "validation:mind-projects:brain-l1-validation-health-contract",
        "node_type": "narrative",
        "subtype": "validation",
        "name": "Validation Â· Brain L1 Project Health Contract",
        "status": "unknown",
        "content": "Valide que l'agrÃ©gation ne masque aucune dimension critique et n'invente aucune mesure.",
    },
]

relations = [
    (project_id, "MONITORED_BY", parent_space),
    (parent_space, "INSTANCE_OF", "space:mind-meta:self-verifying-loop-v0"),
    (parent_space, "HAS_HEALTH", "health:mind-projects:brain-l1-validation"),
    (parent_space, "MEASURED_BY", "metric:mind-projects:brain-l1-validation-health"),
    (parent_space, "OBSERVED_BY", "observer:mind-projects:brain-l1-validation-health"),
    (parent_space, "HAS_OBJECTIVE", "objective:mind-projects:brain-l1-validation-health-honest"),
    (parent_space, "VALIDATED_BY", "validation:mind-projects:brain-l1-validation-health-contract"),
    ("health:mind-projects:brain-l1-validation", "SUMMARIZES", "metric:mind-projects:brain-l1-validation-health"),
    ("observer:mind-projects:brain-l1-validation-health", "OBSERVES", parent_space),
    ("validation:mind-projects:brain-l1-validation-health-contract", "VALIDATES", parent_space),
]

for d in dimensions:
    slug = d["slug"]
    space_id = f"space:mind-projects:brain-l1-{slug}-health-v0"
    health_id = f"health:mind-projects:brain-l1-{slug}"
    metric_id = f"metric:mind-projects:brain-l1-{slug}-health"
    observer_id = f"observer:mind-projects:brain-l1-{slug}-health"
    objective_id = f"objective:mind-projects:brain-l1-{slug}-health-measured"
    validation_id = f"validation:mind-projects:brain-l1-{slug}-health-contract"

    nodes.extend([
        {
            "id": space_id,
            "node_type": "space",
            "subtype": "self_verifying_loop",
            "name": f"Project Health Â· {d['name']} v0",
            "status": "unknown",
            "content": (
                f"Health loop du chantier {d['name']}. Statut initial unknown jusqu'Ã  "
                "mesure rÃ©elle. Produit mÃ©triques, blockers, fraÃ®cheur et readiness locale."
            ),
        },
        {
            "id": health_id,
            "node_type": "narrative",
            "subtype": "health",
            "name": f"Health Â·- Brain L1 {d['name']}",
            "status": "unknown",
            "content": f"RÃ©sumÃ© de santÃ© mesurÃ©e pour {d['name']}.",
        },
        {
            "id": metric_id,
            "node_type": "thing",
            "subtype": "metric",
            "name": f"Metric Â·- Brain L1 {d['name']} Health",
            "status": "unknown",
            "content": json.dumps({
                "criteria": d["criteria"],
                "critical": d["critical"],
                "measurement_status": "not_measured",
                "aggregation": "no_average_masking",
            }, ensure_ascii=False),
        },
        {
            "id": observer_id,
            "node_type": "thing",
            "subtype": "observer",
            "name": f"Observer Â· Brain L1 {d['name']} Health",
            "status": "unknown",
            "content": f"Observe les critÃ¨res {', '.join(d['criteria'])}; signale stale, failed et blockers.",
        },
        {
            "id": objective_id,
            "node_type": "narrative",
            "subtype": "objective",
            "name": f"Mesurer honnÃªtement la santÃ© de {d['name']}",
            "status": "active",
            "content": "Aucune santÃ© positive sans mesure rÃ©elle et traÃ§able.",
        },
        {
            "id": validation_id,
            "node_type": "narrative",
            "subtype": "validation",
            "name": f"Validation Â· Brain L1 {d['name']} Health Contract",
            "status": "unknown",
            "content": "Valide schÃ©ma, fraÃ®cheur, provenance, blockers et transitions de statut.",
        },
    ])

    relations.extend([
        (parent_space, "COMPOSED_OF", space_id),
        (space_id, "INSTANCE_OF", "space:mind-meta:self-verifying-loop-v0"),
        (space_id, "HAS_HEALTH", health_id),
        (space_id, "MEASURED_BY", metric_id),
        (space_id, "OBSERVED_BY", observer_id),
        (space_id, "HAS_OBJECTIVE", objective_id),
        (space_id, "VALIDATED_BY", validation_id),
        (health_id, "SUMMARIZES", metric_id),
        (observer_id, "OBSERVES", space_id),
        (validation_id, "VALIDATES", space_id),
        ("health:mind-projects:brain-l1-validation", "AGGREGATES_HEALTH", health_id),
        ("observer:mind-projects:brain-l1-validation-health", "OBSERVES", health_id),
    ])

# Link existing first task to the contracts health loop.
relations.append((
    "task:mind-brain:evaluation:01-instrument-cognitive-ticks",
    "OCCURRED_IN",
    "space:mind-projects:brain-l1-contracts-orchestration-health-v0"))

# Ensure required pre-existing nodes exist before writing.
required = {
    project_id,
    "space:mind-meta:self-verifying-loop-v0",
    "task:mind-brain:evaluation:01-instrument-cognitive-ticks",
}
rows = store.read(
    "MATCH (n) WHERE n.id IN $ids RETURN collect(n.id)",
    {"ids": list(required)},
)
found = set(rows[0][0] if rows else [])
missing = required - found
if missing:
    raise RuntimeError(f"Missing required nodes: {sorted(missing)}")

# Single graph query: merge all nodes, then statically typed relation groups.
groups = defaultdict(list)
for s, r, t in relations:
    groups[r].append({"source": s, "target": t})

parts = [
    """
    UNWIND $nodes AS row
    MERGE (n:RuntimeNode {id: row.id})
    SET n.node_type = row.node_type,
        n.subtype = row.subtype,
        n.type = row.subtype,
        n.name = row.name,
        n.status = row.status,
        n.content = row.content,
        n.updated_at = timestamp()
    """
]
params = {"nodes": nodes}
for idx, (rtype, pairs) in enumerate(groups.items()):
    key = f"rels_{idx}"
    params[key] = pairs
    parts.append(
        f"""
        WITH 1 AS _
        UNWIND ${key} AS rel
        MATCH (a:RuntimeNode {{id: rel.source}})
        MATCH (b:RuntimeNode {{id: rel.target}})
        MERGE (a)-[:{rtype}]->(b)
        """
    )

query = "\n".join(parts) + "\nRETURN 1"
store.write(query, params)

# Verification.
expected_ids = [n["id"] for n in nodes]
rows = store.read(
    """
    MATCH (n) WHERE n.id IN $ids
    RETURN count(n), collect(n.id)
    """,
    {"ids": expected_ids},
)
count = rows[0][0] if rows else 0
found_ids = set(rows[0][1] if rows else [])
missing_ids = sorted(set(expected_ids) - found_ids)

rel_checks = store.read(
    """
    MATCH (p {id:$project})-[:MONITORED_BY]->(parent {id:$parent})
    OPTIONAL MATCH (parent)-[:COMPOSED_OF]->(child)
    RETURN parent.id, count(child), collect(child.id)
    """,
    {"project": project_id, "parent": parent_space},
)

print(json.dumps({
    "nodes_expected": len(expected_ids),
    "nodes_found": count,
    "missing_nodes": missing_ids,
    "parent_check": rel_checks,
    "relation_count_expected": len(relations),
    "status": "ok" if count == len(expected_ids) and rel_checks else "partial",
}, ensure_ascii=False, indent=2))
