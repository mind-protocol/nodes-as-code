from __future__ import annotations

import json
import time
from pathlib import Path

from .graph import GraphStore
from .hashing import sha256_text

PROGRAM_ID = "code:mind-blueprints:think-in-loops-prompt:v0"
CONTRACT_ID = "contract:mind-blueprints:think-in-loops-prompt:v0"
RULE_ID = "trigger-rule:blueprints:think-in-loops-v0"
DEMO_BLUEPRINT_ID = "space:demo:blueprint-v0"

MATERIALIZER_ID = "code:mind-code:repository-code-materializer:v0"
MATERIALIZER_CONTRACT_ID = "contract:mind-code:repository-code-materializer:v0"
MATERIALIZATION_RULE_ID = "trigger-rule:mind-code:materialize-code-nodes:v0"
MATERIALIZATION_SCHEDULE_ID = "schedule:mind-code:periodic-code-materialization-v0"
MATERIALIZATION_SPACE_ID = "space:mind-code:materialization-v0"
RUNTIME_POLICY_ID = "policy:mind-kernel:daemon-runtime-v0"
DAEMON_ACTOR_ID = "actor:service:mind-kernel-daemon"


def bootstrap(store: GraphStore, project_root: Path) -> None:
    now = int(time.time() * 1000)
    source = (project_root / "programs" / "think_in_loops.md").read_text(encoding="utf-8")
    source_hash = sha256_text(source)
    materializer_source = (project_root / "src" / "mind_node_runtime" / "materialize.py").read_text(
        encoding="utf-8"
    )
    materializer_source_hash = sha256_text(materializer_source)

    input_schema = {
        "type": "object",
        "required": ["blueprintId", "requestedMode"],
        "properties": {
            "blueprintId": {"type": "string"},
            "requestedMode": {"enum": ["create", "audit", "complete"]},
        },
    }
    output_schema = {
        "type": "object",
        "required": [
            "identity",
            "objective",
            "chainInventory",
            "causalChain",
            "debtsAndRisks",
            "nextVerticalIncrement",
            "honestFinalState",
        ],
    }
    materializer_input_schema = {
        "type": "object",
        "required": ["operation", "repoRoot"],
        "properties": {
            "operation": {"enum": ["sync", "resolve"]},
            "repoRoot": {"type": "string"},
            "outputDir": {"type": "string"},
            "graphAuthorityOnly": {"type": "boolean"},
            "programIdToResolve": {"type": "string"},
            "materialize": {"type": "boolean"},
        },
    }
    materializer_output_schema = {
        "type": "object",
        "required": ["status"],
        "properties": {"status": {"type": "string"}},
    }

    store.write(
        """
        MERGE (program:RuntimeNode {id:$program_id})
        SET program.node_type='thing',
            program.subtype='code',
            program.name='Prompt Program · Think in Loops v0',
            program.artifact_kind='prompt_program',
            program.language='prompt_markdown',
            program.authority_mode='graph_source',
            program.version='0.1.0',
            program.source=$source,
            program.source_hash=$source_hash,
            program.executor_type='prompt_program',
            program.fallback_executor='deterministic_blueprint_inventory_v0',
            program.status='active'

        MERGE (contract:RuntimeNode {id:$contract_id})
        SET contract.node_type='thing',
            contract.subtype='prompt_contract',
            contract.name='Contract · Think in Loops v0',
            contract.version='0.1.0',
            contract.input_schema_json=$input_schema_json,
            contract.output_schema_json=$output_schema_json,
            contract.result_type='blueprint_loop_analysis'

        MERGE (rule:RuntimeNode {id:$rule_id})
        SET rule.node_type='thing',
            rule.subtype='trigger_rule',
            rule.name='Trigger · Think in Loops v0',
            rule.status='active',
            rule.version='0.1.0',
            rule.event_types_json=$event_types_json,
            rule.mode_mapping_json=$mode_mapping_json,
            rule.target_node_type='space',
            rule.target_subtype='ontology_module',
            rule.program_id=$program_id,
            rule.contract_id=$contract_id,
            rule.priority=100,
            rule.max_attempts=3

        MERGE (program)-[:USES_CONTRACT]->(contract)
        MERGE (rule)-[:EXECUTES]->(program)
        MERGE (rule)-[:USES_CONTRACT]->(contract)

        MERGE (materialization_space:RuntimeNode {id:$materialization_space_id})
        SET materialization_space.node_type='space',
            materialization_space.subtype='ontology_module',
            materialization_space.name='Loop · Materialization v0',
            materialization_space.status='defining',
            materialization_space.contract_kind='self_verifying_loop',
            materialization_space.content='Derive repository artifacts from graph-authoritative code revisions and resolve live when the local cache is absent or stale.'

        MERGE (materializer:RuntimeNode {id:$materializer_id})
        SET materializer.node_type='thing',
            materializer.subtype='code',
            materializer.name='Code · Repository code materializer v0',
            materializer.artifact_kind='python_script',
            materializer.language='python',
            materializer.authority_mode='graph_source',
            materializer.version='0.1.0',
            materializer.status='active',
            materializer.source=$materializer_source,
            materializer.source_hash=$materializer_source_hash,
            materializer.executor_type='python_script',
            materializer.entrypoint='mind_node_runtime.materialize:execute_materializer'

        MERGE (materializer_contract:RuntimeNode {id:$materializer_contract_id})
        SET materializer_contract.node_type='thing',
            materializer_contract.subtype='program_contract',
            materializer_contract.name='Contract · Repository code materializer v0',
            materializer_contract.version='0.1.0',
            materializer_contract.input_schema_json=$materializer_input_schema_json,
            materializer_contract.output_schema_json=$materializer_output_schema_json,
            materializer_contract.result_type='code_materialization_result'

        MERGE (materialization_rule:RuntimeNode {id:$materialization_rule_id})
        SET materialization_rule.node_type='thing',
            materialization_rule.subtype='trigger_rule',
            materialization_rule.name='Trigger · Materialize code nodes v0',
            materialization_rule.status='active',
            materialization_rule.version='0.1.0',
            materialization_rule.event_types_json=$materialization_event_types_json,
            materialization_rule.program_id=$materializer_id,
            materialization_rule.contract_id=$materializer_contract_id,
            materialization_rule.target_node_type='*',
            materialization_rule.target_subtype='*',
            materialization_rule.mode_mapping_json=$materialization_mode_mapping_json,
            materialization_rule.priority=200,
            materialization_rule.max_attempts=3

        MERGE (materialization_schedule:RuntimeNode {id:$materialization_schedule_id})
        SET materialization_schedule.node_type='thing',
            materialization_schedule.subtype='schedule_policy',
            materialization_schedule.name='Schedule · Periodic code materialization v0',
            materialization_schedule.status='active',
            materialization_schedule.version='0.2.0',
            materialization_schedule.execution_mode='hybrid',
            materialization_schedule.interval_seconds=30.0,
            materialization_schedule.initial_delay_seconds=2.0,
            materialization_schedule.emits_event_type='periodic_code_materialization_tick',
            materialization_schedule.target_program_id=$materializer_id,
            materialization_schedule.target_id=$materialization_space_id,
            materialization_schedule.payload_json=$materialization_schedule_payload_json,
            materialization_schedule.coalescing=true,
            materialization_schedule.created_at=coalesce(materialization_schedule.created_at,$now),
            materialization_schedule.last_emitted_at=coalesce(materialization_schedule.last_emitted_at,0)

        MERGE (daemon_actor:RuntimeNode {id:$daemon_actor_id})
        SET daemon_actor.node_type='actor',
            daemon_actor.subtype='service_actor',
            daemon_actor.name='Mind Kernel Daemon'

        MERGE (runtime_policy:RuntimeNode {id:$runtime_policy_id})
        SET runtime_policy.node_type='thing',
            runtime_policy.subtype='runtime_policy',
            runtime_policy.name='Policy · Mind Kernel Daemon runtime v0',
            runtime_policy.status='active',
            runtime_policy.version='0.1.0',
            runtime_policy.loop_sleep_seconds=0.25,
            runtime_policy.heartbeat_interval_seconds=15.0,
            runtime_policy.watchdog_timeout_seconds=60.0,
            runtime_policy.config_refresh_seconds=2.0

        MERGE (materialization_space)-[:DEFINED_BY_CODE]->(materializer)
        MERGE (materialization_space)-[:HAS_TRIGGER]->(materialization_rule)
        MERGE (materialization_space)-[:HAS_SCHEDULE]->(materialization_schedule)
        MERGE (materialization_rule)-[:EXECUTES]->(materializer)
        MERGE (materialization_rule)-[:USES_CONTRACT]->(materializer_contract)
        MERGE (materializer)-[:USES_CONTRACT]->(materializer_contract)
        MERGE (materialization_schedule)-[:SCHEDULES]->(materializer)
        MERGE (runtime_policy)-[:GOVERNS]->(daemon_actor)

        MERGE (blueprint:RuntimeNode {id:$demo_blueprint_id})
        SET blueprint.node_type='space',
            blueprint.subtype='ontology_module',
            blueprint.name='Demo · Minimal Blueprint',
            blueprint.status='planned',
            blueprint.content='A demo blueprint containing only an objective.'

        MERGE (objective:RuntimeNode {id:'objective:demo:minimal-blueprint'})
        SET objective.node_type='narrative',
            objective.subtype='objective',
            objective.name='Demonstrate graph-authorized Node-as-Code execution',
            objective.content='Prove event → trigger rule → execution intent → run → result without an HTTP API.'

        MERGE (blueprint)-[:CONTAINS]->(objective)
        """,
        {
            "program_id": PROGRAM_ID,
            "contract_id": CONTRACT_ID,
            "rule_id": RULE_ID,
            "demo_blueprint_id": DEMO_BLUEPRINT_ID,
            "source": source,
            "source_hash": source_hash,
            "materialization_space_id": MATERIALIZATION_SPACE_ID,
            "materializer_id": MATERIALIZER_ID,
            "materializer_contract_id": MATERIALIZER_CONTRACT_ID,
            "materialization_rule_id": MATERIALIZATION_RULE_ID,
            "materialization_schedule_id": MATERIALIZATION_SCHEDULE_ID,
            "runtime_policy_id": RUNTIME_POLICY_ID,
            "daemon_actor_id": DAEMON_ACTOR_ID,
            "materializer_source": materializer_source,
            "materializer_source_hash": materializer_source_hash,
            "materialization_event_types_json": json.dumps(
                [
                    "code_node_created",
                    "code_node_changed",
                    "program_revision_activated",
                    "code_materialization_requested",
                    "periodic_code_materialization_tick",
                    "materialization_missing_or_stale",
                ]
            ),
            "materialization_mode_mapping_json": json.dumps(
                {
                    "code_node_created": "sync",
                    "code_node_changed": "sync",
                    "program_revision_activated": "sync",
                    "code_materialization_requested": "resolve",
                    "periodic_code_materialization_tick": "sync",
                    "materialization_missing_or_stale": "resolve",
                },
                sort_keys=True,
            ),
            "materialization_schedule_payload_json": json.dumps(
                {
                    "programId": MATERIALIZER_ID,
                    "contractId": MATERIALIZER_CONTRACT_ID,
                    "inputs": {
                        "operation": "sync",
                        "repoRoot": "$daemon.repo_root",
                        "outputDir": ".mind/generated/code",
                        "graphAuthorityOnly": False,
                    },
                },
                sort_keys=True,
            ),
            "input_schema_json": json.dumps(input_schema, ensure_ascii=False, sort_keys=True),
            "output_schema_json": json.dumps(output_schema, ensure_ascii=False, sort_keys=True),
            "materializer_input_schema_json": json.dumps(
                materializer_input_schema, ensure_ascii=False, sort_keys=True
            ),
            "materializer_output_schema_json": json.dumps(
                materializer_output_schema, ensure_ascii=False, sort_keys=True
            ),
            "event_types_json": json.dumps(
                [
                    "manual_blueprint_analysis_requested",
                    "blueprint_created",
                    "blueprint_status_transition_requested",
                    "manual_code_execution_requested",
                ]
            ),
            "mode_mapping_json": json.dumps(
                {
                    "manual_blueprint_analysis_requested": "complete",
                    "blueprint_created": "create",
                    "blueprint_status_transition_requested": "audit",
                    "manual_code_execution_requested": "complete",
                },
                sort_keys=True,
            ),
            "now": now,
        },
    )

    runtime_sources = {
        "code:mind-kernel:runtime-daemon:v0": (
            "daemon.py",
            "Mind Kernel Runtime Daemon v0",
            "mind_node_runtime.daemon:main",
        ),
        "code:mind-kernel:graph-scheduler:v0": (
            "scheduler.py",
            "Graph-controlled Scheduler v0",
            "mind_node_runtime.scheduler:GraphScheduler",
        ),
        "code:mind-kernel:execution-worker:v0": (
            "worker.py",
            "Graph-authorized Execution Worker v0",
            "mind_node_runtime.worker:Worker",
        ),
        "code:mind-kernel:runtime-watchdog:v0": (
            "watchdog.py",
            "Mind Runtime Watchdog v0",
            "mind_node_runtime.watchdog:main",
        ),
        MATERIALIZER_ID: (
            "materialize.py",
            "Repository code materializer v0",
            "mind_node_runtime.materialize:execute_materializer",
        ),
    }
    package_root = project_root / "src" / "mind_node_runtime"
    for program_id, (filename, name, entrypoint) in runtime_sources.items():
        runtime_source = (package_root / filename).read_text(encoding="utf-8")
        runtime_source_hash = sha256_text(runtime_source)
        store.write(
            """
            MERGE (program:RuntimeNode {id:$program_id})
            SET program.node_type='thing',
                program.subtype='code',
                program.name=$name,
                program.artifact_kind='python_script',
                program.language='python',
                program.authority_mode='graph_source',
                program.version='0.1.0',
                program.status='active',
                program.source=$source,
                program.source_hash=$source_hash,
                program.executor_type='python_script',
                program.entrypoint=$entrypoint
            WITH program
            MATCH (materialization_space {id:$materialization_space_id})
            MERGE (materialization_space)-[:MATERIALIZES_OR_RUNS]->(program)
            RETURN program.id
            """,
            {
                "program_id": program_id,
                "name": name,
                "source": runtime_source,
                "source_hash": runtime_source_hash,
                "entrypoint": entrypoint,
                "materialization_space_id": MATERIALIZATION_SPACE_ID,
            },
        )
