from __future__ import annotations

from pathlib import Path

from mind_node_runtime.runtime_policy import RuntimePolicy
from mind_node_runtime.executors import execute_registered_python_entrypoint
from mind_node_runtime.scheduler import SchedulePolicy, bind_runtime_values, due_at_ms


class FakeCodeStore:
    def __init__(self) -> None:
        self.nodes = [
            {
                "id": "code:test:hello:v0",
                "node_type": "thing",
                "subtype": "code",
                "name": "Hello",
                "version": "0.1.0",
                "language": "python",
                "artifact_kind": "python_script",
                "authority_mode": "graph_source",
                "source": "print('hello')\n",
                "source_hash": None,
                "executor_type": "python_script",
                "content": None,
                "structured_definition_json": None,
                "status": "active",
            }
        ]

    def list_code_nodes(self):
        return self.nodes

    def load_code_node(self, program_id: str):
        return next(node for node in self.nodes if node["id"] == program_id)


def _schedule(**overrides: object) -> SchedulePolicy:
    values = {
        "id": "schedule:test:v0",
        "status": "active",
        "execution_mode": "periodic",
        "interval_seconds": 30.0,
        "initial_delay_seconds": 2.0,
        "last_emitted_at": 0,
        "created_at": 1_000,
        "emits_event_type": "test_tick",
        "target_program_id": "code:test:v0",
        "target_id": "space:test:v0",
        "payload": {},
        "coalescing": True,
    }
    values.update(overrides)
    return SchedulePolicy(**values)


def test_interval_is_read_from_schedule_policy() -> None:
    assert due_at_ms(_schedule(), now_ms=2_000) == 3_000
    assert due_at_ms(_schedule(last_emitted_at=10_000), now_ms=20_000) == 40_000
    assert due_at_ms(_schedule(interval_seconds=10.0, last_emitted_at=10_000), now_ms=20_000) == 20_000


def test_event_driven_schedule_is_not_polled() -> None:
    assert due_at_ms(_schedule(execution_mode="event_driven"), now_ms=50_000) is None


def test_runtime_bindings_are_resolved_from_daemon_context() -> None:
    payload = {
        "inputs": {
            "repoRoot": "$daemon.repo_root",
            "graphName": "$daemon.graph_name",
        }
    }
    assert bind_runtime_values(
        payload,
        {"repo_root": "C:/repo", "graph_name": "mind_kernel_v0"},
    ) == {"inputs": {"repoRoot": "C:/repo", "graphName": "mind_kernel_v0"}}


def test_runtime_policy_is_graph_configurable() -> None:
    policy = RuntimePolicy.from_row([0.1, 12, 45, 1])
    assert policy.loop_sleep_seconds == 0.1
    assert policy.heartbeat_interval_seconds == 12
    assert policy.watchdog_timeout_seconds == 45
    assert policy.config_refresh_seconds == 1


def test_materializer_runs_through_registered_entrypoint(tmp_path: Path) -> None:
    output = execute_registered_python_entrypoint(
        entrypoint="mind_node_runtime.materialize:execute_materializer",
        store=FakeCodeStore(),
        inputs={
            "operation": "sync",
            "repoRoot": str(tmp_path),
            "outputDir": ".mind/generated/code",
        },
    )
    assert output.executor_type == "registered_python_entrypoint_v0"
    assert output.value["status"] == "completed"
    assert output.value["created"] == 1
    assert (tmp_path / ".mind/generated/code/code/test/hello/v0.py").exists()
