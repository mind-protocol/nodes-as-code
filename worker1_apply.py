
from datetime import datetime, timezone
import json
from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
NOW = datetime.now(timezone.utc).isoformat()
CHANGESET_ID = "changeset:mind-runtime:l1-cognitive-cycle-worker1-v0"
AUTHOR = "worker:mind-graphs:1"

contracts = {
"CognitiveTickEnvelope": {
"tick_id":"string","citizen_id":"string","stimulus_id":"string","correlation_id":"string",
"received_at":"datetime","current_stage":"enum","epistemic_status":"enum(observed,inferred,unknown,not_measured,measurement_failed)",
"runtime_budget":"object","trace_refs":"array[string]","errors":"array[TypedError]"},
"PerceptBundle":{"percepts":"array[Percept]","source_refs":"array[string]","unknowns":"array","epistemic_status":"enum"},
"HumanStateFrame":{"capacity_available":"measure","fatigue":"measure","sleep":"measure","pain":"measure","hunger":"measure","hydration":"measure","heat":"measure","relevant_substances":"array","cognitive_load":"measure","urgency":"measure","measurement_freshness":"object"},
"AffectiveNeedState":{"observations":"array","hypotheses":"array","consolidated_state":"object","needs":"array","evidence_refs":"array"},
"StimulusSet":{"seeds":"array[Stimulus]","energy_budget":"number","node_budget":"integer","time_budget_ms":"integer"},
"PropagationResult":{"activated_nodes":"array","dissent_nodes":"array","energy_accounting":"object","stop_reason":"string","trace_id":"string"},
"ContextFrontier":{"resonant_nodes":"array","neutral_nodes":"array","dissent_nodes":"array","retrieval_reasons":"array"},
"ContextPackage":{"shared_reality":"object","resonant_frontier":"array","dissent_frontier":"array","recent_moments":"array","unknowns":"array","permissions":"object","retrieval_trace_id":"string"},
"SubentityActivationSet":{"activations":"array[SubentityActivation]","persistent_actor_refs_only":"boolean","unknowns":"array"},
"WorkspaceBidSet":{"bids":"array[WorkspaceBid]","evidence_refs":"array","unknowns":"array"},
"WorkspaceSnapshot":{"leader":"ref|null","supports":"array[max=3]","objections":"array","active_working_memory":"object","carryover_memory":"object","episodic_tail":"array","constraints":"array","current_plan":"object","version":"string"},
"CognitiveDispatchDecision":{"mode":"enum(rule,worker_1b,local_llm,remote_model,abstention,deferred)","reason":"string","budget":"object","trace_refs":"array"},
"ResponseCandidate":{"factual_claims":"array","inferences":"array","advice":"array","proposed_actions":"array","uncertainties":"array","internal_sources":"array"},
"ValidatedResponse":{"status":"enum(accepted,corrected,reduced_scope,retry,abstained)","response":"string|null","validation_trace":"array","correlation_id":"string"},
"OutcomeObservation":{"response_delivered":"boolean","goal_progress":"measure|null","safety":"measure|null","agency":"measure|null","relationship_quality":"measure|null","metabolic_cost":"measure|null","constitutional_compliance":"number","feedback_status":"enum(observed,unknown,not_measured,measurement_failed)"}
}

g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)
def q(c,p=None):
    return list(g.query(c,p or {}).result_set or [])

# Preconditions: canonical IDs absent or unique.
ids = [
"space:mind-runtime:l1-cognitive-cycle-v0",
"space:mind-maintenance:l1-cognitive-cycle-liveness-v0",
CHANGESET_ID,
]
for cid in contracts:
    ids.append(f"contract:mind-runtime:{cid}:v0")
rows=q("UNWIND $ids AS id OPTIONAL MATCH (n {id:id}) RETURN id, count(n)",{"ids":ids})
dupes=[r for r in rows if int(r[1])>1]
if dupes:
    raise RuntimeError(f"duplicate canonical IDs: {dupes}")

# One atomic graph mutation query.
cypher = """
MERGE (cs:RuntimeNode {id:$changeset_id})
SET cs.node_type='thing', cs.subtype='change_set', cs.name='ChangeSet · L1 Cognitive Cycle Worker 1 v0',
    cs.status='applied', cs.author=$author, cs.source='Brief parallèle — Brain L1 fonctionnel en 5 workers',
    cs.applied_at=$now, cs.atomic=true, cs.rollback_plan='Delete nodes declared by this ChangeSet; restore removed execution edges listed in removed_relations_json',
    cs.removed_relations_json=$removed_relations_json

MERGE (cycle:RuntimeNode {id:'space:mind-runtime:l1-cognitive-cycle-v0'})
SET cycle.node_type='space', cycle.subtype='ontology_module', cycle.name='Loop · L1 Cognitive Cycle v0',
    cycle.status='contracts_defined', cycle.role='runtime_orchestrator',
    cycle.promise='Every accepted inbound tick terminates as responded, abstained, deferred, or typed_error.',
    cycle.version='v0', cycle.updated_at=$now
MERGE (meta {id:'space:mind-meta:self-verifying-loop-v0'})
MERGE (cycle)-[:INSTANCE_OF]->(meta)
MERGE (cs)-[:APPLIES_TO]->(cycle)

MERGE (live:RuntimeNode {id:'space:mind-maintenance:l1-cognitive-cycle-liveness-v0'})
SET live.node_type='space', live.subtype='ontology_module', live.name='Loop · L1 Cognitive Cycle Liveness v0',
    live.status='contracts_defined', live.role='liveness_guard',
    live.promise='Detect and close suspended or multiply-terminated cognitive ticks.',
    live.version='v0', live.updated_at=$now
MERGE (live)-[:INSTANCE_OF]->(meta)
MERGE (cs)-[:APPLIES_TO]->(live)
MERGE (live)-[:OBSERVES]->(cycle)

WITH cs,cycle,live
UNWIND $loop_components AS c
MERGE (n:RuntimeNode {id:c.id})
SET n.node_type=c.node_type, n.subtype=c.subtype, n.name=c.name, n.content=c.content,
    n.status=c.status, n.updated_at=$now
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='HAS_OBJECTIVE' THEN [1] ELSE [] END | MERGE (cycle)-[:HAS_OBJECTIVE]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='HAS_ALGORITHM' THEN [1] ELSE [] END | MERGE (cycle)-[:HAS_ALGORITHM]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='HAS_BEHAVIOR' THEN [1] ELSE [] END | MERGE (cycle)-[:HAS_BEHAVIOR]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='HAS_CODE_DEFINITION' THEN [1] ELSE [] END | MERGE (cycle)-[:HAS_CODE_DEFINITION]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='HAS_IMPLEMENTATION' THEN [1] ELSE [] END | MERGE (cycle)-[:HAS_IMPLEMENTATION]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='TRIGGERED_BY' THEN [1] ELSE [] END | MERGE (cycle)-[:TRIGGERED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='MEASURED_BY' THEN [1] ELSE [] END | MERGE (cycle)-[:MEASURED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='OBSERVED_BY' THEN [1] ELSE [] END | MERGE (cycle)-[:OBSERVED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='HAS_HEALTH' THEN [1] ELSE [] END | MERGE (cycle)-[:HAS_HEALTH]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='VALIDATED_BY' THEN [1] ELSE [] END | MERGE (cycle)-[:VALIDATED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='cycle' AND c.rel='TESTED_BY' THEN [1] ELSE [] END | MERGE (cycle)-[:TESTED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='HAS_OBJECTIVE' THEN [1] ELSE [] END | MERGE (live)-[:HAS_OBJECTIVE]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='HAS_ALGORITHM' THEN [1] ELSE [] END | MERGE (live)-[:HAS_ALGORITHM]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='HAS_BEHAVIOR' THEN [1] ELSE [] END | MERGE (live)-[:HAS_BEHAVIOR]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='HAS_CODE_DEFINITION' THEN [1] ELSE [] END | MERGE (live)-[:HAS_CODE_DEFINITION]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='HAS_IMPLEMENTATION' THEN [1] ELSE [] END | MERGE (live)-[:HAS_IMPLEMENTATION]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='TRIGGERED_BY' THEN [1] ELSE [] END | MERGE (live)-[:TRIGGERED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='MEASURED_BY' THEN [1] ELSE [] END | MERGE (live)-[:MEASURED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='OBSERVED_BY' THEN [1] ELSE [] END | MERGE (live)-[:OBSERVED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='HAS_HEALTH' THEN [1] ELSE [] END | MERGE (live)-[:HAS_HEALTH]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='VALIDATED_BY' THEN [1] ELSE [] END | MERGE (live)-[:VALIDATED_BY]->(n))
FOREACH (_ IN CASE WHEN c.loop='live' AND c.rel='TESTED_BY' THEN [1] ELSE [] END | MERGE (live)-[:TESTED_BY]->(n))
MERGE (cs)-[:DECLARES]->(n)

WITH DISTINCT cs,cycle,live
UNWIND $contracts AS c
MERGE (n:RuntimeNode {id:c.id})
SET n.node_type='thing', n.subtype='data_contract', n.type='schema', n.name=c.name,
    n.version='v0', n.schema_json=c.schema_json, n.epistemic_status='observed',
    n.status='canonical_contract', n.updated_at=$now
MERGE (cycle)-[:DECLARES_CONTRACT]->(n)
MERGE (cs)-[:DECLARES]->(n)

WITH DISTINCT cs,cycle,live
MATCH (stim {id:'space:mind-runtime:stimulate-v0'})
MATCH (prop {id:'space:mind-runtime:propagate-v0'})
OPTIONAL MATCH (stim)-[r1:CONSUMES_OUTPUT_OF|DEPENDS_ON|PRECEDES]->(prop)
DELETE r1
WITH DISTINCT cs,cycle,live,stim,prop
OPTIONAL MATCH (prop)-[r2:DEPENDS_ON|PRECEDES]->(stim)
DELETE r2
WITH DISTINCT cs,cycle,live,stim,prop
OPTIONAL MATCH (stim)-[r3:DEPENDS_ON]->(mcp)
WHERE mcp.id STARTS WITH 'space:l2:mcp:'
DELETE r3
WITH DISTINCT cs,cycle,live,stim,prop
OPTIONAL MATCH (prop)-[r4:DEPENDS_ON]->(mcp2