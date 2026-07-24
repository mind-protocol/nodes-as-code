from __future__ import annotations

import argparse
import json
import signal
import time
from dataclasses import replace
from pathlib import Path

from .bootstrap import DEMO_BLUEPRINT_ID, bootstrap
from .config import Settings
from .daemon import RuntimeDaemon, watchdog
from .events import emit_event
from .graph import GraphStore
from .inspect import snapshot
from .worker import Worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal Mind Node-as-Code runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = sub.add_parser(
        "bootstrap", help="Create programs, contracts, schedules, and demo nodes"
    )
    bootstrap_parser.add_argument("--graph")

    emit = sub.add_parser("emit", help="Write a GraphEvent")
    emit.add_argument("--graph")
    emit.add_argument("--event", default="manual_blueprint_analysis_requested")
    emit.add_argument("--target", default=DEMO_BLUEPRINT_ID)
    emit.add_argument("--mode", choices=["create", "audit", "complete"], default="complete")
    emit.add_argument("--actor", default="actor-nlr")

    worker = sub.add_parser("worker", help="Resolve and execute graph-authorized intents")
    worker.add_argument("--graph")
    worker.add_argument("--once", action="store_true")

    inspect_parser = sub.add_parser("inspect", help="Print recent runtime nodes")
    inspect_parser.add_argument("--graph")

    daemon = sub.add_parser(
        "daemon", help="Run scheduler, worker, heartbeat, and reconciliation continuously"
    )
    daemon.add_argument("--graph")
    daemon.add_argument("--repo", default=".")
    daemon.add_argument("--once", action="store_true")

    watchdog_parser = sub.add_parser(
        "watchdog", help="Check whether the daemon heartbeat is fresh"
    )
    watchdog_parser.add_argument("--graph")
    return parser


def settings_for(args: argparse.Namespace) -> Settings:
    settings = Settings()
    graph_name = getattr(args, "graph", None)
    return replace(settings, graph_name=graph_name) if graph_name else settings


def main() -> None:
    args = build_parser().parse_args()
    settings = settings_for(args)
    store = GraphStore(settings)
    root = Path(__file__).resolve().parents[2]

    if args.command == "bootstrap":
        bootstrap(store, root)
        print(json.dumps({"status": "ok", "graph": settings.graph_name}, indent=2))
        return

    if args.command == "emit":
        event_id = emit_event(
            store,
            event_type=args.event,
            target_id=args.target,
            source_actor_id=args.actor,
            payload={"requestedMode": args.mode},
        )
        print(json.dumps({"eventId": event_id}, indent=2))
        return

    if args.command == "inspect":
        print(json.dumps(snapshot(store), ensure_ascii=False, indent=2))
        return

    if args.command == "watchdog":
        result = watchdog(store)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["status"] == "alive" else 2)

    if args.command == "daemon":
        daemon = RuntimeDaemon(store, settings, Path(args.repo))
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signal_name, daemon.request_stop)
        daemon.run(once=args.once)
        return

    worker = Worker(store, settings)
    if args.once:
        print(json.dumps(worker.tick(), ensure_ascii=False, indent=2))
        return
    while True:
        outcome = worker.tick()
        if any(value for value in outcome.values()):
            print(json.dumps(outcome, ensure_ascii=False))
        time.sleep(settings.poll_seconds)
