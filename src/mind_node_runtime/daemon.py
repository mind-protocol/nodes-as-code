from __future__ import annotations

import argparse
import json
import signal
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Settings
from .graph import GraphStore
from .runtime_policy import RuntimePolicy
from .scheduler import GraphScheduler
from .worker import Worker

RUNTIME_POLICY_ID = "policy:mind-kernel:daemon-runtime-v0"
DAEMON_ACTOR_ID = "actor:service:mind-kernel-daemon"
DAEMON_HEALTH_ID = "health:mind-kernel:daemon-liveness"
DAEMON_PROBLEM_ID = "problem:mind-kernel:daemon-heartbeat-stale"
SOURCE_INTEGRITY_PROBLEM_ID = "problem:mind-kernel:runtime-source-integrity"

RUNTIME_SOURCE_NODES = {
    "code:mind-kernel:runtime-daemon:v0": "daemon.py",
    "code:mind-kernel:graph-scheduler:v0": "scheduler.py",
    "code:mind-kernel:execution-worker:v0": "worker.py",
    "code:mind-kernel:runtime-watchdog:v0": "watchdog.py",
    "code:mind-code:repository-code-materializer:v0": "materialize.py",
}



def verify_runtime_source_integrity(store: GraphStore) -> dict[str, Any]:
    from .hashing import sha256_text

    package_root = Path(__file__).resolve().parent
    mismatches: list[dict[str, str]] = []
    for program_id, filename in RUNTIME_SOURCE_NODES.items():
        try:
            node = store.load_code_node(program_id)
        except KeyError:
            mismatches.append({"programId": program_id, "reason": "graph_code_node_missing"})
            continue
        local_source = (package_root / filename).read_text(encoding="utf-8")
        graph_source = node.get("source")
        graph_hash = str(node.get("source_hash") or "")
        expected_hash = graph_hash or (sha256_text(graph_source) if isinstance(graph_source, str) else "")
        local_hash = sha256_text(local_source)
        if not expected_hash or expected_hash != local_hash:
            mismatches.append(
                {
                    "programId": program_id,
                    "reason": "source_hash_mismatch",
                    "graphHash": expected_hash,
                    "localHash": local_hash,
                }
            )

    now_ms = int(time.time() * 1000)
    if mismatches:
        store.write(
            """
            MERGE (problem:RuntimeNode {id:$problem_id})
            SET problem.node_type='narrative', problem.subtype='problem',
                problem.name='Installed Mind runtime differs from graph-authoritative source',
                problem.status='open', problem.information_status='measured',
                problem.observed_behavior=$observed,
                problem.exact_difference='One or more installed runtime modules do not match their active graph source hashes.',
                problem.recommended_action='Materialize the active graph sources, review them, update the installed package, then restart the daemon.',
                problem.last_detected_at=$now
            RETURN problem.id
            """,
            {
                "problem_id": SOURCE_INTEGRITY_PROBLEM_ID,
                "observed": json.dumps(mismatches, ensure_ascii=False, sort_keys=True),
                "now": now_ms,
            },
        )
        raise RuntimeError(
            "installed runtime source integrity failed: "
            + json.dumps(mismatches, ensure_ascii=False)
        )

    store.write(
        """
        MATCH (problem {id:$problem_id})
        SET problem.status='resolved', problem.resolved_at=$now
        RETURN problem.id
        """,
        {"problem_id": SOURCE_INTEGRITY_PROBLEM_ID, "now": now_ms},
    )
    return {"status": "verified", "programCount": len(RUNTIME_SOURCE_NODES)}

def load_runtime_policy(store: GraphStore) -> RuntimePolicy:
    rows = store.read(
        """
        MATCH (policy {id:$id})
        RETURN policy.loop_sleep_seconds,
               policy.heartbeat_interval_seconds,
               policy.watchdog_timeout_seconds,
               policy.config_refresh_seconds
        """,
        {"id": RUNTIME_POLICY_ID},
    )
    return RuntimePolicy.from_row(rows[0] if rows else None)


class RuntimeDaemon:
    def __init__(self, store: GraphStore, settings: Settings, repo_root: Path) -> None:
        self.store = store
        self.settings = settings
        self.repo_root = repo_root.resolve()
        self.worker = Worker(store, settings)
        self.scheduler = GraphScheduler(store)
        self.instance_id = f"daemon-instance:{uuid.uuid4()}"
        self.stop_requested = False
        self.policy = RuntimePolicy()
        self._next_policy_refresh = 0.0
        self._next_heartbeat = 0.0

    def request_stop(self, *_: object) -> None:
        self.stop_requested = True

    def refresh_policy(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now >= self._next_policy_refresh:
            self.policy = load_runtime_policy(self.store)
            self._next_policy_refresh = now + self.policy.config_refresh_seconds

    def heartbeat(self) -> str:
        now_ms = int(time.time() * 1000)
        slot = int(now_ms / max(1000, int(self.policy.heartbeat_interval_seconds * 1000)))
        heartbeat_id = f"heartbeat:{self.instance_id}:{slot}"
        rows = self.store.write(
            """
            MERGE (actor:RuntimeNode {id:$actor_id})
            SET actor.node_type='actor',
                actor.subtype='service_actor',
                actor.name='Mind Kernel Daemon'
            MERGE (instance:RuntimeNode {id:$instance_id})
            SET instance.node_type='thing',
                instance.subtype='runtime_instance',
                instance.name='Mind Kernel Daemon Instance',
                instance.status='running',
                instance.graph_name=$graph_name,
                instance.repo_root=$repo_root,
                instance.worker_id=$worker_id,
                instance.last_heartbeat_at=$now,
                instance.started_at=coalesce(instance.started_at,$now)
            MERGE (heartbeat:RuntimeNode {id:$heartbeat_id})
            ON CREATE SET heartbeat.node_type='moment',
                          heartbeat.subtype='daemon_heartbeat',
                          heartbeat.status='measured',
                          heartbeat.emitted_at=$now,
                          heartbeat.graph_name=$graph_name,
                          heartbeat.repo_root=$repo_root,
                          heartbeat.instance_id=$instance_id
            MERGE (instance)-[:INSTANCE_OF]->(actor)
            MERGE (heartbeat)-[:HEARTBEAT_OF]->(instance)
            RETURN heartbeat.id
            """,
            {
                "actor_id": DAEMON_ACTOR_ID,
                "instance_id": self.instance_id,
                "heartbeat_id": heartbeat_id,
                "graph_name": self.settings.graph_name,
                "repo_root": str(self.repo_root),
                "worker_id": self.settings.worker_id,
                "now": now_ms,
            },
        )
        return str(rows[0][0]) if rows else heartbeat_id

    def stop_instance(self) -> None:
        try:
            self.store.write(
                """
                MATCH (instance {id:$instance_id})
                SET instance.status='stopped', instance.stopped_at=$now
                """,
                {"instance_id": self.instance_id, "now": int(time.time() * 1000)},
            )
        except Exception:
            pass

    def tick(self) -> dict[str, Any]:
        self.refresh_policy()
        now = time.monotonic()
        heartbeat_id = None
        if now >= self._next_heartbeat:
            heartbeat_id = self.heartbeat()
            self._next_heartbeat = now + self.policy.heartbeat_interval_seconds

        scheduler_outcome = self.scheduler.tick(
            runtime_context={
                "repo_root": str(self.repo_root),
                "graph_name": self.settings.graph_name,
                "worker_id": self.settings.worker_id,
            }
        )
        worker_outcome = self.worker.tick()
        return {
            "heartbeatId": heartbeat_id,
            "scheduler": scheduler_outcome,
            "worker": worker_outcome,
        }

    def run(self, *, once: bool = False) -> None:
        verify_runtime_source_integrity(self.store)
        self.refresh_policy(force=True)
        self.heartbeat()
        self._next_heartbeat = time.monotonic() + self.policy.heartbeat_interval_seconds
        try:
            while not self.stop_requested:
                outcome = self.tick()
                if once:
                    print(json.dumps(outcome, ensure_ascii=False, indent=2))
                    return
                if (
                    outcome["heartbeatId"]
                    or outcome["scheduler"]["emittedEvents"]
                    or outcome["scheduler"]["errors"]
                    or any(outcome["worker"].values())
                ):
                    print(json.dumps(outcome, ensure_ascii=False), flush=True)
                time.sleep(self.policy.loop_sleep_seconds)
        finally:
            self.stop_instance()


def watchdog(store: GraphStore) -> dict[str, Any]:
    policy = load_runtime_policy(store)
    now_ms = int(time.time() * 1000)
    rows = store.read(
        """
        MATCH (instance)
        WHERE instance.node_type='thing'
          AND instance.subtype='runtime_instance'
        RETURN instance.id, instance.status, instance.last_heartbeat_at,
               instance.graph_name, instance.repo_root
        ORDER BY instance.last_heartbeat_at DESC
        LIMIT 1
        """
    )
    latest = rows[0] if rows else None
    timeout_ms = int(policy.watchdog_timeout_seconds * 1000)
    last_heartbeat = int(latest[2] or 0) if latest else 0
    age_ms = now_ms - last_heartbeat if last_heartbeat else None
    alive = (
        latest is not None
        and str(latest[1]) == "running"
        and age_ms is not None
        and age_ms <= timeout_ms
    )

    if alive:
        store.write(
            """
            MERGE (health:RuntimeNode {id:$health_id})
            SET health.node_type='narrative', health.subtype='health',
                health.name='Health · Mind Kernel Daemon liveness',
                health.status='healthy', health.information_status='measured',
                health.last_assessed_at=$now,
                health.last_heartbeat_at=$last_heartbeat,
                health.valid_until=$valid_until
            RETURN health.id
            """,
            {
                "health_id": DAEMON_HEALTH_ID,
                "now": now_ms,
                "last_heartbeat": last_heartbeat,
                "valid_until": last_heartbeat + timeout_ms,
            },
        )
        store.write(
            """
            MATCH (problem {id:$problem_id})
            SET problem.status='resolved', problem.resolved_at=$now
            RETURN problem.id
            """,
            {"problem_id": DAEMON_PROBLEM_ID, "now": now_ms},
        )
        return {
            "status": "alive",
            "instanceId": latest[0],
            "heartbeatAgeSeconds": round(age_ms / 1000, 3),
            "timeoutSeconds": policy.watchdog_timeout_seconds,
        }

    information_status = "known_absent" if latest is None else "measured"
    observed = "no daemon heartbeat exists" if latest is None else f"latest heartbeat is {age_ms / 1000:.1f}s old"
    store.write(
        """
        MERGE (actor:RuntimeNode {id:$actor_id})
        SET actor.node_type='actor', actor.subtype='service_actor', actor.name='Mind Kernel Daemon'
        MERGE (problem:RuntimeNode {id:$problem_id})
        SET problem.node_type='narrative',
            problem.subtype='problem',
            problem.name='Mind Kernel Daemon heartbeat is stale or absent',
            problem.status='open',
            problem.information_status=$information_status,
            problem.expected_behavior='A daemon heartbeat must be observed inside the graph-defined watchdog window.',
            problem.observed_behavior=$observed,
            problem.exact_difference='No fresh heartbeat proves the runtime is currently alive.',
            problem.watchdog_timeout_seconds=$timeout_seconds,
            problem.last_heartbeat_at=$last_heartbeat,
            problem.last_detected_at=$now,
            problem.recommended_action='Restart the OS-managed Mind Node Runtime task and inspect the daemon logs.'
        MERGE (problem)-[:CONCERNS]->(actor)
        MERGE (health:RuntimeNode {id:$health_id})
        SET health.node_type='narrative', health.subtype='health',
            health.name='Health · Mind Kernel Daemon liveness',
            health.status='degraded', health.information_status=$information_status,
            health.last_assessed_at=$now,
            health.valid_until=$now
        MERGE (health)-[:EXPLAINS_WITH]->(problem)
        RETURN problem.id
        """,
        {
            "actor_id": DAEMON_ACTOR_ID,
            "problem_id": DAEMON_PROBLEM_ID,
            "health_id": DAEMON_HEALTH_ID,
            "information_status": information_status,
            "observed": observed,
            "timeout_seconds": policy.watchdog_timeout_seconds,
            "last_heartbeat": last_heartbeat,
            "now": now_ms,
        },
    )
    return {
        "status": "stale_or_absent",
        "instanceId": latest[0] if latest else None,
        "heartbeatAgeSeconds": round(age_ms / 1000, 3) if age_ms is not None else None,
        "timeoutSeconds": policy.watchdog_timeout_seconds,
        "informationStatus": information_status,
    }


def settings_for_graph(graph_name: str | None) -> Settings:
    settings = Settings()
    return replace(settings, graph_name=graph_name) if graph_name else settings


def build_daemon_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the graph-controlled Mind Node Runtime daemon")
    parser.add_argument("--graph")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> None:
    args = build_daemon_parser().parse_args()
    settings = settings_for_graph(args.graph)
    store = GraphStore(settings)
    daemon = RuntimeDaemon(store, settings, Path(args.repo))
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_name, daemon.request_stop)
    daemon.run(once=args.once)


if __name__ == "__main__":
    main()
