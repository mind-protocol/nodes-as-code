from __future__ import annotations

import argparse
import json

from .daemon import settings_for_graph, watchdog
from .graph import GraphStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the graph-recorded Mind daemon heartbeat")
    parser.add_argument("--graph")
    args = parser.parse_args()
    settings = settings_for_graph(args.graph)
    try:
        result = watchdog(GraphStore(settings))
    except Exception as exc:
        print(json.dumps({"status": "measurement_failed", "error": repr(exc)}, indent=2))
        raise SystemExit(3)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "alive" else 2)


if __name__ == "__main__":
    main()
