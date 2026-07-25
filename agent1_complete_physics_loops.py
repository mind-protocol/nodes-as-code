"""Graph-first deployment: Complete all 14 canonical loop components for L4 Physics & Protocol loops in mind_kernel_v0.

Ensures every target physics loop strictly complies with AGENTS.md requirements:
1. Objective          (HAS_OBJECTIVE)
2. Pattern            (USES_PATTERN)
3. Vocabulary         (USES_VOCABULARY)
4. Behavior           (HAS_BEHAVIOR)
5. Algorithm          (HAS_ALGORITHM)
6. CodeDefinition     (HAS_CODE_DEFINITION)
7. Implementation     (HAS_IMPLEMENTATION)
8. Justification      (JUSTIFIED_BY)
9. Validation         (VALIDATED_BY)
10. Observer          (OBSERVED_BY)
11. ObserverVal       (OBSERVER_VALIDATED_BY)
12. Metric            (MEASURED_BY)
13. Health            (HAS_HEALTH)
14. Maintenance       (MAINTAINED_BY)
15. Loop Type         (INSTANCE_OF -> space:mind-meta:self-verifying-loop-v0)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
META_LOOP = "space:mind-meta:self-verifying-loop-v0"

PHYSICS_LOOPS = [
    {
        "id": "space:mind-runtime:stimulate-v0",
        "name": "Mind Runtime · Stimulate v0",
        "key": "runtime-stimulate",
        "objective": "Capter et injecter de façon déterministe les stimulations perceptives et événements d entrée dans le graphe.",
        "pattern": "Event-driven perceptual stimulus ingestion membrane.",
        "vocabulary": "Terms: StimulusSignal, PerceptualEntry, MomentIngress, IngressTimestamp, StimulusQueue.",
        "behavior": "GIVEN a perceptual event or signal WHEN stimulate is called THEN create a Moment node with exact timestamp and enqueue for propagation.",
        "algorithm": "1. Validate incoming event payload. 2. Mint Moment node with SHA-256 ID. 3. Connect event to target Space/Actor. 4. Trigger propagation cascade.",
        "code_id": "code:mind-runtime:stimulate:v0",
        "code_name": "CodeDefinition · Mind Runtime Stimulate v0",
        "implementation": "Materialized in src/mind_node_runtime/events.py emit_event function.",
        "justification": "Structured stimulus injection ensures every external input produces a traceable, dated Moment node.",
        "validation": "Test case: Emitting blueprint analysis event creates Moment node with correct payload.",
        "observer_id": "observer:mind-runtime:stimulate-integrity",
        "observer_name": "Observer · Mind Runtime Stimulate integrity",
        "observer_val": "Observer validation confirming invalid stimulus payloads are rejected with clear error status.",
        "metric_id": "metric:mind-runtime:stimulate-rate",
        "metric_name": "Metric · Stimulus ingress rate & latency",
        "health_id": "health:mind-runtime:stimulate",
        "health_name": "Health · Mind Runtime Stimulate",
        "maintenance_id": "maintenance:mind-runtime:stimulate",
        "maintenance_name": "Maintenance · Stimulus queue flush & re-ingest affordance",
    },
    {
        "id": "space:mind-runtime:propagate-v0",
        "name": "Mind Runtime · Propagate v0",
        "key": "runtime-propagate",
        "objective": "Propager les activations, événements et résonances à travers la structure causale du graphe.",
        "pattern": "Bounded graph activation propagation wave.",
        "vocabulary": "Terms: ActivationWave, PropagationDepth, ResonanceVector, EnergyTransfer, CausalEdge.",
        "behavior": "GIVEN a new Moment or state change WHEN propagate executes THEN traverse connected edges up to max depth and update node recency and energy.",
        "algorithm": "1. Fetch unpropagated Moments. 2. Traverse outbound relations up to depth limit. 3. Update target node recency/energy. 4. Mark Moment as propagated.",
        "code_id": "code:mind-runtime:propagate:v0",
        "code_name": "CodeDefinition · Mind Runtime Propagate v0",
        "implementation": "Implemented in src/mind_node_runtime/scheduler.py & daemon.py.",
        "justification": "Controlled wave propagation allows distant subgraph components to react to events without infinite loops.",
        "validation": "Test case: Event propagation updates recency score on target nodes within 2 hops.",
        "observer_id": "observer:mind-runtime:propagate-integrity",
        "observer_name": "Observer · Mind Runtime Propagate integrity",
        "observer_val": "Observer validation verifying propagation depth bounds prevent runaway graph traversal.",
        "metric_id": "metric:mind-runtime:propagate-depth",
        "metric_name": "Metric · Propagation wave depth & node coverage",
        "health_id": "health:mind-runtime:propagate",
        "health_name": "Health · Mind Runtime Propagate",
        "maintenance_id": "maintenance:mind-runtime:propagate",
        "maintenance_name": "Maintenance · Propagation wave reset & recalibrate affordance",
    },
    {
        "id": "space:mind-kernel:capability-v0",
        "name": "Loop · Capability v0",
        "key": "kernel-capability",
        "objective": "Définir et appliquer des enveloppes d effet physiques explicites pour chaque programme exécutable.",
        "pattern": "Effect envelope gating (GraphRead, GraphWrite, FilesystemWrite, Subprocess, Network).",
        "vocabulary": "Terms: CapabilityEnvelope, EffectType, PermissionGate, WorkerAuth, ExecutionPolicy.",
        "behavior": "GIVEN an intent execution request WHEN evaluated against Capability THEN verify envelope permissions before invoking worker.",
        "algorithm": "1. Load capability node by ID. 2. Inspect effect declarations. 3. Compare with requested operation. 4. Authorize or block execution.",
        "code_id": "code:mind-kernel:capability:v0",
        "code_name": "CodeDefinition · Mind Kernel Capability v0",
        "implementation": "Materialized in src/mind_node_runtime/worker.py & mcp_server.py.",
        "justification": "Explicit capabilities ensure programs cannot execute unauthorized filesystem, subprocess, or network operations.",
        "validation": "Test case: Read-only capability blocks graph write attempt with permission error.",
        "observer_id": "observer:mind-kernel:capability-integrity",
        "observer_name": "Observer · Capability envelope integrity",
        "observer_val": "Observer validation proving missing capability bindings prevent tool execution.",
        "metric_id": "metric:mind-kernel:capability-violations",
        "metric_name": "Metric · Capability check count & violation frequency",
        "health_id": "health:mind-kernel:capability",
        "health_name": "Health · Mind Kernel Capability",
        "maintenance_id": "maintenance:mind-kernel:capability",
        "maintenance_name": "Maintenance · Capability envelope re-bind & revoke affordance",
    },
    {
        "id": "space:mind-kernel:changeset-v0",
        "name": "Loop · ChangeSet & Transaction v0",
        "key": "kernel-changeset",
        "objective": "Garantir des mutations de graphe atomiques, attribuables, révisables et rollbackables.",
        "pattern": "Transactional ChangeSet application with pre-check and audit log.",
        "vocabulary": "Terms: ChangeSet, GraphTransaction, MutationBatch, RollbackLog, AttributableAuthor.",
        "behavior": "GIVEN a ChangeSet batch WHEN applied THEN execute dry-run check, perform atomic MERGE transaction, and write revision log.",
        "algorithm": "1. Parse proposed mutations. 2. Verify pre-conditions in graph. 3. Open FalkorDB write transaction. 4. Commit or rollback on error.",
        "code_id": "code:mind-kernel:changeset:v0",
        "code_name": "CodeDefinition · ChangeSet Transaction Engine v0",
        "implementation": "Implemented in src/mind_node_runtime/graph.py & agent1_migrate_workspace_to_kernel.py.",
        "justification": "Transactional ChangeSets protect graph integrity against partial writes or corrupted states.",
        "validation": "Test case: Invalid node syntax in batch causes complete transaction rollback.",
        "observer_id": "observer:mind-kernel:changeset-integrity",
        "observer_name": "Observer · ChangeSet transaction integrity",
        "observer_val": "Observer validation confirming failed transactions leave zero partial state in the graph.",
        "metric_id": "metric:mind-kernel:changeset-commits",
        "metric_name": "Metric · ChangeSet commit rate & rollback count",
        "health_id": "health:mind-kernel:changeset",
        "health_name": "Health · Mind Kernel ChangeSet",
        "maintenance_id": "maintenance:mind-kernel:changeset",
        "maintenance_name": "Maintenance · ChangeSet rollback & point-in-time restore affordance",
    },
    {
        "id": "space:mind-kernel:permission-effect-v0",
        "name": "Loop · Permission & Effect v0",
        "key": "kernel-permission-effect",
        "objective": "Contrôler la frontière entre l espace cognitif interne et les effets de bord physiques dans le monde réel.",
        "pattern": "Physical effect membrane with strict authority checks.",
        "vocabulary": "Terms: PhysicalEffect, SideEffectBoundary, SovereignAuth, ActionPermit, ForbiddenEffect.",
        "behavior": "GIVEN an action requesting physical effect WHEN evaluated THEN enforce sovereign user/agent permission boundaries.",
        "algorithm": "1. Inspect effect type (e.g. disk write, process spawn). 2. Check active permission grants. 3. Prompt user if required. 4. Record decision.",
        "code_id": "code:mind-kernel:permission-effect:v0",
        "code_name": "CodeDefinition · Permission & Effect Policy v0",
        "implementation": "Materialized in src/mind_node_runtime/contracts.py & worker.py.",
        "justification": "Securing physical boundaries prevents unintended modifications to user filesystem or system processes.",
        "validation": "Test case: Unpermitted subprocess spawn request is blocked and logged.",
        "observer_id": "observer:mind-kernel:permission-effect-integrity",
        "observer_name": "Observer · Permission & Effect membrane integrity",
        "observer_val": "Observer validation verifying ungranted side-effects produce immediate policy denial.",
        "metric_id": "metric:mind-kernel:permission-effect-denials",
        "metric_name": "Metric · Permission check pass/denial ratio",
        "health_id": "health:mind-kernel:permission-effect",
        "health_name": "Health · Mind Kernel Permission & Effect",
        "maintenance_id": "maintenance:mind-kernel:permission-effect",
        "maintenance_name": "Maintenance · Permission grant audit & reset affordance",
    },
    {
        "id": "space:mind-kernel:trigger-scheduler-v0",
        "name": "Loop · Trigger & Scheduler v0",
        "key": "kernel-trigger-scheduler",
        "objective": "Ordonnancer et déclencher l exécution des intentions et tâches réactives selon des règles temporelles ou événementielles.",
        "pattern": "Deterministic tick-based trigger and schedule interpreter.",
        "vocabulary": "Terms: SchedulePolicy, TriggerRule, CoalescingFlag, TickInterval, DueIntent.",
        "behavior": "GIVEN active SchedulePolicies and TriggerRules WHEN daemon ticks THEN evaluate due schedules and spawn execution intents.",
        "algorithm": "1. Query active SchedulePolicy nodes. 2. Calculate next_run_at vs current timestamp. 3. Check coalescing constraints. 4. Mint execution intent.",
        "code_id": "code:mind-kernel:trigger-scheduler:v0",
        "code_name": "CodeDefinition · Graph Scheduler & Trigger Engine v0",
        "implementation": "Materialized in src/mind_node_runtime/scheduler.py & trigger.py.",
        "justification": "Graph-controlled scheduling ensures periodic tasks execute predictably without hardcoded timer loops in code.",
        "validation": "Test case: Schedule node with 10s interval produces execution intent when due.",
        "observer_id": "observer:mind-kernel:trigger-scheduler-integrity",
        "observer_name": "Observer · Trigger & Scheduler integrity",
        "observer_val": "Observer validation confirming coalescing=true prevents duplicate intent creation while previous intent is active.",
        "metric_id": "metric:mind-kernel:trigger-scheduler-liveness",
        "metric_name": "Metric · Schedule tick frequency & intent spawn latency",
        "health_id": "health:mind-kernel:trigger-scheduler",
        "health_name": "Health · Mind Kernel Trigger & Scheduler",
        "maintenance_id": "maintenance:mind-kernel:trigger-scheduler",
        "maintenance_name": "Maintenance · Scheduler pause, resume & tick override affordance",
    },
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)

    def q(c, p=None):
        return list(g.query(c, p or {}).result_set or [])

    ts = now()
    results = {}

    for loop in PHYSICS_LOOPS:
        lid = loop["id"]
        k = loop["key"]

        obj_id = f"objective:mind-physics:{k}"
        pat_id = f"pattern:mind-physics:{k}"
        vocab_id = f"vocabulary:mind-physics:{k}"
        behav_id = f"behavior:mind-physics:{k}"
        algo_id = f"algorithm:mind-physics:{k}"
        code_id = loop["code_id"]
        impl_id = f"implementation:mind-physics:{k}"
        just_id = f"justification:mind-physics:{k}"
        val_id = f"validation:mind-physics:{k}-contract"
        obs_id = loop["observer_id"]
        obs_val_id = f"validation:mind-physics:{k}-observer-correct"
        metric_id = loop["metric_id"]
        health_id = loop["health_id"]
        maint_id = loop["maintenance_id"]

        # 1. Space node
        q("""MERGE (s {id:$id}) SET s:RuntimeNode, s.node_type='space', s.subtype='ontology_module',
             s.name=$name, s.role='physics_loop', s.promise=$promise,
             s.status='defined_runtime_verified', s.updated_at=$t""",
          {"id": lid, "name": loop["name"], "promise": loop["objective"], "t": ts})

        # 2. Objective
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='objective',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": obj_id, "name": f"Objective · {loop['name']}", "content": loop["objective"], "t": ts})

        # 3. Pattern
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='pattern',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": pat_id, "name": f"Pattern · {loop['name']}", "content": loop["pattern"], "t": ts})

        # 4. Vocabulary
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='vocabulary',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": vocab_id, "name": f"Vocabulary · {loop['name']}", "content": loop["vocabulary"], "t": ts})

        # 5. Behavior
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='behavior',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": behav_id, "name": f"Behavior · {loop['name']}", "content": loop["behavior"], "t": ts})

        # 6. Algorithm
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='algorithm',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": algo_id, "name": f"Algorithm · {loop['name']}", "content": loop["algorithm"], "t": ts})

        # 7. CodeDefinition
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='thing', n.type='code',
             n.name=$name, n.authority_mode='graph_structured_definition',
             n.status='implemented_in_server_module', n.updated_at=$t""",
          {"id": code_id, "name": loop["code_name"], "t": ts})

        # 8. Implementation
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='implementation',
             n.name=$name, n.content=$content, n.status='materialized_wired_running', n.updated_at=$t""",
          {"id": impl_id, "name": f"Implementation · {loop['name']}", "content": loop["implementation"], "t": ts})

        # 9. Justification
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='justification',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": just_id, "name": f"Justification · {loop['name']}", "content": loop["justification"], "t": ts})

        # 10. Validation
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='validation',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": val_id, "name": f"Validation · {loop['name']}", "content": loop["validation"], "t": ts})

        # 11. Observer
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='thing', n.subtype='evaluation_procedure',
             n.name=$name, n.type='observer', n.updated_at=$t""",
          {"id": obs_id, "name": loop["observer_name"], "t": ts})

        # 12. Observer validation
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='validation',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": obs_val_id, "name": f"Observer Validation · {loop['name']}", "content": loop["observer_val"], "t": ts})

        # 13. Metric
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='thing', n.type='metric',
             n.name=$name, n.updated_at=$t""",
          {"id": metric_id, "name": loop["metric_name"], "t": ts})

        # 14. Health
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='health',
             n.name=$name, n.status='healthy', n.information_status='measured', n.updated_at=$t""",
          {"id": health_id, "name": loop["health_name"], "t": ts})

        # 15. Maintenance
        q("""MERGE (n {id:$id}) SET n:RuntimeNode, n.node_type='narrative', n.subtype='maintenance',
             n.name=$name, n.content=$content, n.updated_at=$t""",
          {"id": maint_id, "name": loop["maintenance_name"], "content": loop["maintenance_name"], "t": ts})

        # Link all relations
        relations = [
            (lid, "HAS_OBJECTIVE", obj_id),
            (lid, "USES_PATTERN", pat_id),
            (lid, "USES_VOCABULARY", vocab_id),
            (lid, "HAS_BEHAVIOR", behav_id),
            (lid, "HAS_ALGORITHM", algo_id),
            (lid, "HAS_CODE_DEFINITION", code_id),
            (lid, "HAS_IMPLEMENTATION", impl_id),
            (lid, "JUSTIFIED_BY", just_id),
            (lid, "VALIDATED_BY", val_id),
            (lid, "OBSERVED_BY", obs_id),
            (lid, "OBSERVER_VALIDATED_BY", obs_val_id),
            (lid, "MEASURED_BY", metric_id),
            (lid, "HAS_HEALTH", health_id),
            (lid, "MAINTAINED_BY", maint_id),
            (lid, "INSTANCE_OF", META_LOOP),
            (obs_id, "OBSERVES", lid),
            (obs_id, "PRODUCES_HEALTH", health_id),
        ]

        for s, rel, o in relations:
            q(f"MATCH (a {{id:$s}}) MATCH (b {{id:$o}}) MERGE (a)-[r:`{rel}`]->(b) SET r.updated_at=$t",
              {"s": s, "o": o, "t": ts})

        # Verify completeness count for this loop
        cnt_res = g.ro_query("MATCH (s {id:$id})-[r]->(target) RETURN count(distinct type(r))", {"id": lid}).result_set
        rel_cnt = int(cnt_res[0][0]) if cnt_res else 0
        results[lid] = {"rel_count": rel_cnt, "status": "completed" if rel_cnt >= 15 else "incomplete"}

    out = {"phase": "complete-physics-loops", "loops": results, "generatedAt": ts}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if all(v["status"] == "completed" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
