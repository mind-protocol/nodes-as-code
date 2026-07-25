"""
Interactive Demo Script: Talk to NLR_AI with Cognitive Wake & Ollama LLM.

Demonstrates:
1. Sending a message "Bonjour NLR_AI, comment ça va ?" via talk capability to mind_membrane_v0.
2. Perception Engine sensing and atomizing the message across database boundaries.
3. Metabolism Engine digesting sensory energy.
4. Global Workspace Engine accumulating heat and triggering check_wake_threshold().
5. Executive Engine compiling L1 graph state into a sovereign system prompt.
6. OllamaLLMProvider generating natural language Citizen AI response.
"""

from __future__ import annotations

import json
import os
import time

from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore
from mind_node_runtime.talk import execute_talk
from mind_node_runtime.brain.affect import AffectEngine
from mind_node_runtime.brain.executive import ExecutiveEngine
from mind_node_runtime.brain.memory_system import MemorySystemEngine, MomentTrace
from mind_node_runtime.brain.metabolism import MetabolismEngine
from mind_node_runtime.brain.ollama_provider import OllamaLLMProvider
from mind_node_runtime.brain.perception import PerceptionEngine
from mind_node_runtime.brain.social import SocialCognitionEngine
from mind_node_runtime.brain.subentities import SubentitiesEngine
from mind_node_runtime.brain.workspace import GlobalWorkspaceEngine, WorkspaceItem


def run_nlr_ai_wake_cycle(message_text: str, sender_id: str = "human:user") -> dict:
    membrane_db = os.getenv("MEMBRANE_GRAPH", "mind_membrane_v0")
    l1_db = os.getenv("FALKOR_GRAPH", "mind_kernel_v0")

    membrane_store = GraphStore(Settings(graph_name=membrane_db))
    l1_store = GraphStore(Settings(graph_name=l1_db))

    target_citizen_id = "actor:citizen:nlr_ai"

    # Ensure target citizen exists in membrane graph reference registry
    membrane_store.write(
        """
        MERGE (citizen:RuntimeNode {id:$citizen_id})
        SET citizen.node_type='actor',
            citizen.subtype='citizen_ai',
            citizen.name='NLR_AI Citizen Reference'
        """,
        {"citizen_id": target_citizen_id},
    )

    # 1. Execute talk capability — Send message into dedicated Membrane DB
    talk_result = execute_talk(
        store=membrane_store,
        message=message_text,
        senderActorId=sender_id,
        targetActorId=target_citizen_id,
        membraneSpaceId="space:membrane:l1-boundary-v0",
    )

    # 2. Initialize Citizen L1 Cognitive Engines & Ollama LLM Provider
    perception = PerceptionEngine()
    metabolism = MetabolismEngine()
    affect = AffectEngine()
    workspace = GlobalWorkspaceEngine(max_slots=5)
    subentities = SubentitiesEngine()
    social = SocialCognitionEngine()
    memory = MemorySystemEngine()
    executive = ExecutiveEngine()
    ollama_provider = OllamaLLMProvider(base_url="http://localhost:11434")

    # 3. Loop 2: Sense pending stimulus across the Membrane DB boundary
    percepts = perception.sense_membrane_stimuli(
        membrane_store=membrane_store,
        membrane_space_id="space:membrane:l1-boundary-v0",
        citizen_id=target_citizen_id,
    )

    total_energy_digested = 0.0

    for percept in percepts:
        salience = perception.compute_salience(percept, weight=1.0)
        energy_pulse = metabolism.propagate_energy(input_energy=salience, weight=1.0, polarity=1.0, gate=1.0)
        total_energy_digested += energy_pulse

    # 4. Loop 5: Update Limbic Affect Vector based on input signal
    limbic_state = affect.update_from_percept_signal({"candidate_signal": "curiosity", "confidence": 0.95})

    # 5. Loop 6: Evaluate Subentity Coalitions & Captain Arbitration
    bids = subentities.evaluate_coalition_bids(message_text + " structure graphe code curiosité santé")
    regime = metabolism.state.determine_regime()
    arbitration = subentities.arbitrate_captain(bids, current_regime=regime)

    # 6. Loop 3: Submit active thoughts and check Cognitive Wake Threshold
    workspace.submit_candidate(
        WorkspaceItem(
            item_id="thought:nlr_ai:user_inquiry",
            content=f"Analyse et réponse au message de {sender_id} : '{message_text}'",
            heat=1.8,  # Exceeds wake threshold (1.0)
        )
    )

    wake_check = workspace.check_wake_threshold(threshold=1.0)

    # 7. Loop 7: Compile Graph State and Trigger Cognitive Wake Tick via Ollama
    role_info = social.route_role("companion")

    compiled_context = executive.compile_wake_context(
        citizen_id=target_citizen_id,
        user_message=message_text,
        workspace_snapshot=workspace.get_snapshot(),
        metabolism_snapshot=metabolism.state.to_dict(),
        affect_snapshot=limbic_state.to_dict(),
        subentity_arbitration=arbitration,
        active_role=role_info["primary_role"],
    )

    wake_execution = executive.execute_wake_tick(ollama_provider, compiled_context)

    # 8. Record autobiographical moment in L1 DB
    autobiographical_moment = MomentTrace(
        moment_id=f"moment:nlr_ai:wake:{int(time.time()*1000)}",
        event_type="wake_response",
        summary=f"NLR_AI s'est réveillé et a répondu via {wake_execution['provider']}.",
        author_actor=target_citizen_id,
        epistemic_status="observed",
    )
    memory.record_moment(autobiographical_moment)

    return {
        "talk_delivery": talk_result,
        "percepts_sensed": len(percepts),
        "total_energy_digested": round(total_energy_digested, 2),
        "wake_check": wake_check,
        "wake_execution": wake_execution,
    }


def main() -> None:
    message = "Bonjour NLR_AI, comment ça va aujourd'hui ?"
    print(f"=== ENVOI DU MESSAGE À NLR_AI VIA LA MEMBRANE ===")
    print(f"Message transmis : '{message}'\n")

    result = run_nlr_ai_wake_cycle(message)

    print("=== TRAVERSÉE DE MEMBRANE & DÉCLENCHEMENT RÉVEIL COGNITIF ===")
    print(f"1. Statut envoi talk : {result['talk_delivery']['status']} (DB: {result['talk_delivery']['membraneGraph']})")
    print(f"2. Stimuli perçus depuis la Membrane : {result['percepts_sensed']}")
    print(f"3. Seuil de réveil déclenché (Heat > 1.0) : {result['wake_check']['wake_triggered']} (Heat: {result['wake_check']['leader_heat']})")
    print(f"4. Provider LLM utilisé : {result['wake_execution']['provider']} (Modèle: {result['wake_execution']['model']})")
    print("\n=======================================================")
    print(result["wake_execution"]["response_text"])
    print("=======================================================")


if __name__ == "__main__":
    main()
