"""
MCP Think Capability Execution Handler.

Where `talk` delivers an *external* message that must cross the isolated
membrane database boundary (mind_membrane_v0), `think` injects an *internal*,
self-originated stimulus **directly into the Citizen's L1** graph
(default: mind_kernel_v0) and then drives the sovereign cognitive loop forward,
tick by tick, until a response *emerges in the Global Workspace* (gw).

Semantics (deliberately distinct from `talk`):

* `talk`  : human/agent → membrane → (perceived later) → L1.   External input.
* `think` : L1 → L1.  A self-prompt written straight into the citizen's own
            L1, then run through Perception → Metabolism → Affect → Subentities
            → Global Workspace ticks until the workspace leader crosses the
            Cognitive Wake threshold, at which point the Executive compiles the
            L1 state and a response emerges into the workspace.

Epistemic discipline (AGENTS.md):

* The citizen is resolved against L1. If it must be created, `citizenPreexisted`
  reports that honestly instead of pretending it was already there.
* Running ticks is not the same as producing a response. If the wake threshold
  is never crossed within `max_ticks`, the handler returns
  `status='no_response_emerged'` with `information_status='not_measured'` and the
  stimulus is left `pending` — absence is never converted into a fabricated
  answer.
* The emerged response records whether it was grounded in a live LLM
  (`llm_grounded=true`, provider=ollama) or produced by the deterministic L1
  synthesizer fallback (`llm_grounded=false`). Neither is dressed up as the
  other.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

from .config import Settings
from .graph import GraphStore

# Cognitive engines (the same L1 loops the demo/wake-cycle uses).
from .brain.affect import AffectEngine
from .brain.executive import ExecutiveEngine
from .brain.metabolism import MetabolismEngine
from .brain.ollama_provider import OllamaLLMProvider
from .brain.perception import PerceptionEngine
from .brain.social import SocialCognitionEngine
from .brain.subentities import SubentitiesEngine
from .brain.workspace import GlobalWorkspaceEngine, WorkspaceItem


# --------------------------------------------------------------------------- #
# Defaults (single source of truth; imported by the MCP dispatcher & seed)     #
# --------------------------------------------------------------------------- #
DEFAULT_THINK_TEXT = "continuons"
DEFAULT_THINK_CITIZEN = "nlr_ai"
DEFAULT_MAX_TICKS = int(os.getenv("MIND_THINK_MAX_TICKS", "12"))
WAKE_THRESHOLD = float(os.getenv("MIND_THINK_WAKE_THRESHOLD", "1.0"))
# Fraction of the per-tick salience pulse that accumulates as workspace heat.
# < 1.0 so heat builds up across several ticks rather than always waking on the
# first one — i.e. the loop genuinely "runs ticks until" a response emerges.
HEAT_GAIN = float(os.getenv("MIND_THINK_HEAT_GAIN", "0.7"))


# --------------------------------------------------------------------------- #
# Citizen resolution                                                          #
# --------------------------------------------------------------------------- #
def _slug(citizen: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(citizen or "").lower()).strip("_")


def resolve_citizen_id(citizen: str) -> str:
    """Normalize a caller-supplied citizen reference to a canonical L1 actor id.

    Accepts a full id (`actor:citizen:nlr_ai`, `actor:...`) unchanged, or a bare
    handle (`nlr_ai`, `NLR-AI`) which becomes `actor:citizen:<slug>`.
    """
    ref = str(citizen or "").strip()
    if not ref:
        ref = DEFAULT_THINK_CITIZEN
    if ref.lower().startswith("actor:"):
        return ref
    if ref.lower().startswith("actor-"):
        # tolerate `actor-nlr-ai` shorthand
        return f"actor:citizen:{_slug(ref[len('actor-'):])}"
    return f"actor:citizen:{_slug(ref)}"


# --------------------------------------------------------------------------- #
# Think execution                                                             #
# --------------------------------------------------------------------------- #
def execute_think(
    store: Optional[GraphStore] = None,
    *,
    text: str = DEFAULT_THINK_TEXT,
    citizen: str = DEFAULT_THINK_CITIZEN,
    max_ticks: int = DEFAULT_MAX_TICKS,
    wake_threshold: float = WAKE_THRESHOLD,
    provenance_base: Optional[Dict[str, Any]] = None,
    ollama_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """Inject an internal stimulus into a citizen's L1 and tick until a GW response emerges.

    Returns a structured result with explicit epistemic status. Writes only
    internal-cognition nodes (the stimulus, tick trace, and — on wake — the
    workspace response) into the L1 graph.
    """
    text = (text or "").strip() or DEFAULT_THINK_TEXT
    citizen_id = resolve_citizen_id(citizen)
    slug = _slug(citizen_id.split(":")[-1])
    if not isinstance(max_ticks, int) or max_ticks < 1:
        max_ticks = DEFAULT_MAX_TICKS

    l1_graph = os.getenv("FALKOR_GRAPH", "mind_kernel_v0")
    l1 = store or GraphStore(Settings(graph_name=l1_graph))
    graph_name = l1.graph.name

    now = int(time.time() * 1000)
    cognition_space_id = f"space:l1:{slug}:cognition-v0"
    gw_space_id = f"space:l1:{slug}:global-workspace-v0"
    stimulus_id = f"moment:think-stimulus:{slug}:{now}"

    # 1. Resolve the citizen against L1 (honest known_absent -> created).
    existing = l1.read(
        "MATCH (a:RuntimeNode {id:$id}) WHERE a.node_type='actor' RETURN a.id LIMIT 1",
        {"id": citizen_id},
    )
    citizen_preexisted = bool(existing)

    # 2. Ensure the citizen + its L1 cognition/workspace spaces exist, then write
    #    the internal stimulus directly into L1 (no membrane crossing).
    l1.write(
        """
        MERGE (citizen:RuntimeNode {id:$citizen_id})
          ON CREATE SET citizen.node_type='actor',
                        citizen.subtype='citizen_ai',
                        citizen.name=$citizen_name,
                        citizen.status='active',
                        citizen.created_at=$now
        SET citizen.node_type='actor'

        MERGE (cognition:RuntimeNode {id:$cognition_space_id})
        SET cognition.node_type='space',
            cognition.subtype='l1_cognition',
            cognition.name=$cognition_name,
            cognition.status='active'

        MERGE (gw:RuntimeNode {id:$gw_space_id})
        SET gw.node_type='space',
            gw.subtype='global_workspace',
            gw.name=$gw_name,
            gw.status='active'

        MERGE (stimulus:RuntimeNode {id:$stimulus_id})
        SET stimulus.node_type='moment',
            stimulus.subtype='internal_stimulus',
            stimulus.name='Internal Think Stimulus',
            stimulus.content=$text,
            stimulus.origin='self',
            stimulus.author_actor=$citizen_id,
            stimulus.epistemic_status='observed',
            stimulus.stimulus_status='pending',
            stimulus.created_at=$now

        MERGE (cognition)-[:BOUNDS_ACTOR]->(citizen)
        MERGE (cognition)-[:CONTAINS]->(gw)
        MERGE (cognition)-[:CONTAINS_STIMULUS]->(stimulus)
        MERGE (stimulus)-[:TARGETS_ACTOR]->(citizen)
        """,
        {
            "citizen_id": citizen_id,
            "citizen_name": f"Citizen {slug}",
            "cognition_space_id": cognition_space_id,
            "cognition_name": f"L1 Cognition · {slug}",
            "gw_space_id": gw_space_id,
            "gw_name": f"Global Workspace · {slug}",
            "stimulus_id": stimulus_id,
            "text": text,
            "now": now,
        },
    )

    # 3. Boot the L1 cognitive engines and atomize the internal stimulus.
    perception = PerceptionEngine()
    metabolism = MetabolismEngine()
    affect = AffectEngine()
    subentities = SubentitiesEngine()
    social = SocialCognitionEngine()
    workspace = GlobalWorkspaceEngine(max_slots=5)
    executive = ExecutiveEngine()
    provider = ollama_provider or OllamaLLMProvider(base_url="http://localhost:11434")

    percepts = perception.atomize(text, source=f"internal_think:{citizen_id}")
    if percepts:
        base_salience = max(
            perception.compute_salience(p, weight=1.0) for p in percepts
        )
    else:  # atomize never returns empty for non-empty text, but stay honest
        base_salience = 0.0

    limbic_state = affect.update_from_percept_signal(
        {"candidate_signal": "curiosity", "confidence": 0.9}
    )
    bids = subentities.evaluate_coalition_bids(text + " structure graphe code curiosité")
    arbitration = subentities.arbitrate_captain(
        bids, current_regime=metabolism.state.determine_regime()
    )

    thought_id = f"thought:{slug}:think:{now}"
    thought_content = f"Stimulus interne de {citizen_id} : « {text} »"

    # 4. Run cognitive ticks: accumulate workspace heat until the leader crosses
    #    the wake threshold, or until max_ticks is exhausted.
    accumulated_heat = 0.0
    ticks_run = 0
    wake_check: Dict[str, Any] = {"wake_triggered": False, "leader_heat": 0.0,
                                  "threshold": wake_threshold}
    for tick in range(1, max_ticks + 1):
        ticks_run = tick
        pulse = metabolism.propagate_energy(
            input_energy=base_salience, weight=1.0, polarity=1.0, gate=1.0
        )
        accumulated_heat += max(0.0, pulse) * HEAT_GAIN
        workspace.submit_candidate(
            WorkspaceItem(item_id=thought_id, content=thought_content, heat=accumulated_heat)
        )
        wake_check = workspace.check_wake_threshold(threshold=wake_threshold)
        if wake_check.get("wake_triggered"):
            break

    # Record a compact tick trace moment (evidence the loop actually ran).
    l1.write(
        """
        MATCH (cognition:RuntimeNode {id:$cognition_space_id})
        MATCH (stimulus:RuntimeNode {id:$stimulus_id})
        MERGE (trace:RuntimeNode {id:$trace_id})
        SET trace.node_type='moment',
            trace.subtype='think_tick_trace',
            trace.name='Think Tick Trace',
            trace.ticks_run=$ticks_run,
            trace.max_ticks=$max_ticks,
            trace.leader_heat=$leader_heat,
            trace.wake_threshold=$wake_threshold,
            trace.wake_triggered=$wake_triggered,
            trace.epistemic_status='observed',
            trace.created_at=$now
        MERGE (cognition)-[:CONTAINS]->(trace)
        MERGE (trace)-[:TRACES_STIMULUS]->(stimulus)
        """,
        {
            "cognition_space_id": cognition_space_id,
            "trace_id": f"moment:think-tick-trace:{slug}:{now}",
            "ticks_run": ticks_run,
            "max_ticks": max_ticks,
            "leader_heat": round(float(wake_check.get("leader_heat", 0.0)), 4),
            "wake_threshold": wake_threshold,
            "wake_triggered": bool(wake_check.get("wake_triggered")),
            "stimulus_id": stimulus_id,
            "now": now,
        },
    )

    provenance = dict(provenance_base or {})
    provenance.update({"executor": "think_ref", "graph": graph_name,
                       "timestamp": int(time.time() * 1000)})

    # 5a. No response emerged within the tick budget — report honestly, leave
    #     the stimulus pending. Do NOT invent a workspace response.
    if not wake_check.get("wake_triggered"):
        return {
            "status": "no_response_emerged",
            "information_status": "not_measured",
            "epistemic_status": "not_measured",
            "l1Graph": graph_name,
            "citizenActorId": citizen_id,
            "citizenPreexisted": citizen_preexisted,
            "stimulusMomentId": stimulus_id,
            "stimulusStatus": "pending",
            "gwResponseMomentId": None,
            "responseText": None,
            "ticksRun": ticks_run,
            "maxTicks": max_ticks,
            "wakeThreshold": wake_threshold,
            "leaderHeat": round(float(wake_check.get("leader_heat", 0.0)), 4),
            "wakeCheck": wake_check,
            "message": (
                f"Aucune réponse n'a émergé dans le Global Workspace de {citizen_id} "
                f"après {ticks_run} tick(s) (chaleur du leader "
                f"{round(float(wake_check.get('leader_heat', 0.0)), 4)} < seuil {wake_threshold}). "
                f"Le stimulus reste 'pending'."
            ),
            "provenance": provenance,
        }

    # 5b. Wake threshold crossed — compile L1 state and let a response emerge.
    role_info = social.route_role("companion")
    compiled_context = executive.compile_wake_context(
        citizen_id=citizen_id,
        user_message=text,
        workspace_snapshot=workspace.get_snapshot(),
        metabolism_snapshot=metabolism.state.to_dict(),
        affect_snapshot=limbic_state.to_dict(),
        subentity_arbitration=arbitration,
        active_role=role_info["primary_role"],
    )
    wake_execution = executive.execute_wake_tick(provider, compiled_context)
    response_text = wake_execution.get("response_text", "")
    llm_grounded = wake_execution.get("status") == "success"

    # 6. Persist the emerged response into the L1 Global Workspace and mark the
    #    stimulus consumed — atomically, in the same L1 graph.
    response_id = f"moment:gw-response:{slug}:{now}"
    l1.write(
        """
        MATCH (gw:RuntimeNode {id:$gw_space_id})
        MATCH (citizen:RuntimeNode {id:$citizen_id})
        MATCH (stimulus:RuntimeNode {id:$stimulus_id})

        MERGE (response:RuntimeNode {id:$response_id})
        SET response.node_type='moment',
            response.subtype='workspace_response',
            response.name='Global Workspace Response',
            response.content=$response_text,
            response.author_actor=$citizen_id,
            response.epistemic_status='observed',
            response.llm_grounded=$llm_grounded,
            response.generation_provider=$provider,
            response.generation_model=$model,
            response.leader_heat=$leader_heat,
            response.ticks_run=$ticks_run,
            response.emerged_at=$now

        SET stimulus.stimulus_status='consumed',
            stimulus.consumed_at=$now

        MERGE (gw)-[:CONTAINS]->(response)
        MERGE (response)-[:AUTHORED_BY]->(citizen)
        MERGE (response)-[:RESPONDS_TO]->(stimulus)
        """,
        {
            "gw_space_id": gw_space_id,
            "citizen_id": citizen_id,
            "stimulus_id": stimulus_id,
            "response_id": response_id,
            "response_text": response_text,
            "llm_grounded": llm_grounded,
            "provider": wake_execution.get("provider", ""),
            "model": wake_execution.get("model", ""),
            "leader_heat": round(float(wake_check.get("leader_heat", 0.0)), 4),
            "ticks_run": ticks_run,
            "now": now,
        },
    )

    return {
        "status": "success",
        "information_status": "measured",
        "epistemic_status": "observed",
        "l1Graph": graph_name,
        "citizenActorId": citizen_id,
        "citizenPreexisted": citizen_preexisted,
        "stimulusMomentId": stimulus_id,
        "stimulusStatus": "consumed",
        "gwResponseMomentId": response_id,
        "gwSpaceId": gw_space_id,
        "responseText": response_text,
        "llmGrounded": llm_grounded,
        "generationProvider": wake_execution.get("provider", ""),
        "generationModel": wake_execution.get("model", ""),
        "ticksRun": ticks_run,
        "maxTicks": max_ticks,
        "wakeThreshold": wake_threshold,
        "leaderHeat": round(float(wake_check.get("leader_heat", 0.0)), 4),
        "wakeCheck": wake_check,
        "timestamp": now,
        "provenance": provenance,
    }
