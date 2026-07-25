"""
Brain Function Loops Seed Script.

Creates all 9 Brain Function Loops in mind_kernel_v0 with full causal chains:
Space -> Objective -> Pattern -> Behavior -> CodeDefinition -> Observer -> Health Definition.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

BRAIN_LOOPS_SPEC = [
    {
        "id": "space:brain:metabolism-v0",
        "name": "Loop 1 · Substrat, Énergie & Régulation",
        "objective_id": "objective:brain:metabolism:primary",
        "objective_name": "Preserve energy conservation and metabolic homeostasis",
        "objective_text": "Propagate energy according to I = E * W * P * G without energy creation, monitor metabolic snapshot (fatigue, pain, hunger, recovery), and manage capacity regimes.",
        "pattern_id": "pattern:brain:metabolism:homeostasis",
        "pattern_name": "Homeostatic Energy Modulation",
        "behavior_id": "behavior:brain:metabolism:decay-and-recover",
        "behavior_text": "GIVEN metabolic inputs WHEN energy drops below threshold THEN set regime to STRAINED/DEPLETED and request rest.",
        "code_id": "code:brain:metabolism-engine:v0",
        "code_name": "Metabolism Engine v0",
        "entrypoint": "mind_node_runtime.brain.metabolism:MetabolismEngine",
        "observer_id": "code:brain:metabolism-observer:v0",
        "observer_name": "Metabolism Observer v0",
    },
    {
        "id": "space:brain:perception-v0",
        "name": "Loop 2 · Sensation, Perception & Attention",
        "objective_id": "objective:brain:perception:primary",
        "objective_name": "Atomize input signals into sourcetracked Percepts and compute salience",
        "objective_text": "Atomize raw sensory text into PerceptAtoms, calculate novelty decay by hash, and derive salience S = E * W * N * P.",
        "pattern_id": "pattern:brain:perception:salience-competition",
        "pattern_name": "Percept Atomization and Salience Filter",
        "behavior_id": "behavior:brain:perception:filter-and-rank",
        "behavior_text": "GIVEN raw text stream WHEN atomized THEN assign energy/priority and rank by computed salience.",
        "code_id": "code:brain:perception-engine:v0",
        "code_name": "Perception Engine v0",
        "entrypoint": "mind_node_runtime.brain.perception:PerceptionEngine",
        "observer_id": "code:brain:perception-observer:v0",
        "observer_name": "Perception Observer v0",
    },
    {
        "id": "space:brain:workspace-v0",
        "name": "Loop 3 · Global Workspace & Active Working Memory",
        "objective_id": "objective:brain:workspace:primary",
        "objective_name": "Broadcast conscious content under strict slot and character budget",
        "objective_text": "Maintain competition for 5 active slots, select temporary leader, track carryover memory (5 moments), and episodic tail.",
        "pattern_id": "pattern:brain:workspace:slot-competition",
        "pattern_name": "Global Workspace Slot Competition",
        "behavior_id": "behavior:brain:workspace:compete-and-broadcast",
        "behavior_text": "GIVEN candidate workspace items WHEN submitted THEN evict item with lowest heat minus monopolization penalty.",
        "code_id": "code:brain:workspace-engine:v0",
        "code_name": "Global Workspace Engine v0",
        "entrypoint": "mind_node_runtime.brain.workspace:GlobalWorkspaceEngine",
        "observer_id": "code:brain:workspace-observer:v0",
        "observer_name": "Workspace Observer v0",
    },
    {
        "id": "space:brain:memory-v0",
        "name": "Loop 4 · Systèmes de Mémoire",
        "objective_id": "objective:brain:memory:primary",
        "objective_name": "Maintain autobiographical Moments, semantic Narratives, and epistemic firewall",
        "objective_text": "Record sourcetracked Moments with explicit epistemic status, prevent self-confirmation, and execute graph rerank.",
        "pattern_id": "pattern:brain:memory:epistemic-firewall",
        "pattern_name": "Epistemic Firewall and Graph Rerank",
        "behavior_id": "behavior:brain:memory:record-and-firewall",
        "behavior_text": "GIVEN new claim WHEN checked against existing claims THEN reject direct contradictions and self-confirmations.",
        "code_id": "code:brain:memory-engine:v0",
        "code_name": "Memory System Engine v0",
        "entrypoint": "mind_node_runtime.brain.memory_system:MemorySystemEngine",
        "observer_id": "code:brain:memory-observer:v0",
        "observer_name": "Memory System Observer v0",
    },
    {
        "id": "space:brain:affect-v0",
        "name": "Loop 5 · Besoins, Affects & Émotions",
        "objective_id": "objective:brain:affect:primary",
        "objective_name": "Maintain continuous multi-dimensional limbic state and emotional regulation",
        "objective_text": "Track arousal, valence, dominance, curiosity, frustration, threat_level, and trigger emotional prototype transitions.",
        "pattern_id": "pattern:brain:affect:limbic-vector",
        "pattern_name": "Continuous Limbic State Vector",
        "behavior_id": "behavior:brain:affect:evaluate-and-regulate",
        "behavior_text": "GIVEN percept signals WHEN threat or frustration spikes THEN trigger alert prototype and suggest homeostatic strategy.",
        "code_id": "code:brain:affect-engine:v0",
        "code_name": "Affect Engine v0",
        "entrypoint": "mind_node_runtime.brain.affect:AffectEngine",
        "observer_id": "code:brain:affect-observer:v0",
        "observer_name": "Affect Observer v0",
    },
    {
        "id": "space:brain:subentities-v0",
        "name": "Loop 6 · Personnalité, Sous-entités & Coalitions",
        "objective_id": "objective:brain:subentities:primary",
        "objective_name": "Track recurring coalitions, SubentityHypotheses, and Captain arbitration",
        "objective_text": "Match activation against subentity signatures, generate WorkspaceBids, and arbitrate via Integrated Captain.",
        "pattern_id": "pattern:brain:subentities:coalition-bidding",
        "pattern_name": "Coalition Matching and Captain Arbitration",
        "behavior_id": "behavior:brain:subentities:bid-and-arbitrate",
        "behavior_text": "GIVEN workspace context WHEN bids generated THEN Captain selects leader preserving internal dissent.",
        "code_id": "code:brain:subentities-engine:v0",
        "code_name": "Subentities Engine v0",
        "entrypoint": "mind_node_runtime.brain.subentities:SubentitiesEngine",
        "observer_id": "code:brain:subentities-observer:v0",
        "observer_name": "Subentities Observer v0",
    },
    {
        "id": "space:brain:executive-v0",
        "name": "Loop 7 · Cognition, Raisonnement & Fonctions Exécutives",
        "objective_id": "objective:brain:executive:primary",
        "objective_name": "Process cortical stacks, scenario confidence, and action proposals under Kernel guardrails",
        "objective_text": "Evaluate scenario confidence C = (P * E) * (1 - Contradiction), enforce permission invariants and safe action execution.",
        "pattern_id": "pattern:brain:executive:trusted-kernel-guardrail",
        "pattern_name": "Trusted Kernel Executive Guardrail",
        "behavior_id": "behavior:brain:executive:propose-and-verify",
        "behavior_text": "GIVEN action proposal WHEN checked by Kernel THEN grant execution only if permissions and policies pass.",
        "code_id": "code:brain:executive-engine:v0",
        "code_name": "Executive Engine v0",
        "entrypoint": "mind_node_runtime.brain.executive:ExecutiveEngine",
        "observer_id": "code:brain:executive-observer:v0",
        "observer_name": "Executive Observer v0",
    },
    {
        "id": "space:brain:plasticity-v0",
        "name": "Loop 8 · Apprentissage & Plasticité",
        "objective_id": "objective:brain:plasticity:primary",
        "objective_name": "Update slow associative weights based on prediction error and reinforce patterns",
        "objective_text": "Calculate prediction error, adjust behavior pattern weights via REINFORCES or WEAKENS, check procedural compilation eligibility.",
        "pattern_id": "pattern:brain:plasticity:prediction-error-learning",
        "pattern_name": "Prediction Error Associative Learning",
        "behavior_id": "behavior:brain:plasticity:error-and-update",
        "behavior_text": "GIVEN expected vs actual outcome WHEN error computed THEN update pattern weight by learning rate * error.",
        "code_id": "code:brain:plasticity-engine:v0",
        "code_name": "Plasticity Engine v0",
        "entrypoint": "mind_node_runtime.brain.plasticity:PlasticityEngine",
        "observer_id": "code:brain:plasticity-observer:v0",
        "observer_name": "Plasticity Observer v0",
    },
    {
        "id": "space:brain:social-v0",
        "name": "Loop 9 · Cognition Sociale, Rôles & Action",
        "objective_id": "objective:brain:social:primary",
        "objective_name": "Maintain Other Model frames, Citizen AI role routing, and human ratification logging",
        "objective_text": "Frame external actor intent preserving opacity, route Citizen AI roles (one primary, max 3 support), and log human ratification.",
        "pattern_id": "pattern:brain:social:role-routing-and-ratification",
        "pattern_name": "Role Routing and Human Ratification",
        "behavior_id": "behavior:brain:social:route-and-ratify",
        "behavior_text": "GIVEN domain context WHEN role routed THEN perform clean handoff and link human ratification Moment.",
        "code_id": "code:brain:social-engine:v0",
        "code_name": "Social Cognition Engine v0",
        "entrypoint": "mind_node_runtime.brain.social:SocialCognitionEngine",
        "observer_id": "code:brain:social-observer:v0",
        "observer_name": "Social Cognition Observer v0",
    },
]


def seed_brain_loops(store: Any) -> Dict[str, Any]:
    created = []
    for spec in BRAIN_LOOPS_SPEC:
        store.write(
            """
            MERGE (space:RuntimeNode {id:$space_id})
            SET space.node_type='space',
                space.subtype='ontology_module',
                space.name=$space_name,
                space.status='active',
                space.contract_kind='self_verifying_loop',
                space.content=$space_name

            MERGE (obj:RuntimeNode {id:$obj_id})
            SET obj.node_type='narrative',
                obj.subtype='objective',
                obj.name=$obj_name,
                obj.content=$obj_text

            MERGE (pat:RuntimeNode {id:$pat_id})
            SET pat.node_type='narrative',
                pat.subtype='pattern',
                pat.name=$pat_name

            MERGE (beh:RuntimeNode {id:$beh_id})
            SET beh.node_type='narrative',
                beh.subtype='behavior',
                beh.name=$beh_name,
                beh.content=$beh_text

            MERGE (code:RuntimeNode {id:$code_id})
            SET code.node_type='thing',
                code.subtype='code',
                code.name=$code_name,
                code.artifact_kind='python_script',
                code.language='python',
                code.authority_mode='graph_source',
                code.version='0.1.0',
                code.status='active',
                code.executor_type='python_script',
                code.entrypoint=$entrypoint

            MERGE (obs:RuntimeNode {id:$obs_id})
            SET obs.node_type='thing',
                obs.subtype='observer',
                obs.name=$obs_name,
                obs.status='active'

            MERGE (space)-[:CONTAINS]->(obj)
            MERGE (space)-[:HAS_PATTERN]->(pat)
            MERGE (space)-[:HAS_BEHAVIOR]->(beh)
            MERGE (space)-[:DEFINED_BY_CODE]->(code)
            MERGE (space)-[:OBSERVED_BY]->(obs)
            MERGE (code)-[:SERVES_OBJECTIVE]->(obj)
            """,
            {
                "space_id": spec["id"],
                "space_name": spec["name"],
                "obj_id": spec["objective_id"],
                "obj_name": spec["objective_name"],
                "obj_text": spec["objective_text"],
                "pat_id": spec["pattern_id"],
                "pat_name": spec["pattern_name"],
                "beh_id": spec["behavior_id"],
                "beh_name": spec["behavior_id"],
                "beh_text": spec["behavior_text"],
                "code_id": spec["code_id"],
                "code_name": spec["code_name"],
                "entrypoint": spec["entrypoint"],
                "obs_id": spec["observer_id"],
                "obs_name": spec["observer_name"],
            },
        )
        created.append(spec["id"])

    return {"status": "success", "seeded_loops_count": len(created), "loops": created}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the 9 Brain Function Loops in mind_kernel_v0.")
    parser.add_argument("--graph", default=os.getenv("FALKOR_GRAPH", "mind_kernel_v0"))
    args = parser.parse_args()

    from .config import Settings
    from .graph import GraphStore

    settings = Settings(graph_name=args.graph)
    store = GraphStore(settings)
    result = seed_brain_loops(store)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
