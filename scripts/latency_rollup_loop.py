"""Always-on response-latency rollup loop.

Reads the raw per-call response-time stream written by the `flux_latency`
decorator (agent1-migration/response-times.jsonl) and, on a fixed interval,
folds a bounded window of it into ONE graph Metric node plus ONE derived Health
node. It never writes to the graph per request — that would tax the very hot
path being measured — so this loop is the single graph writer for the latency
loop.

Epistemic discipline (CLAUDE.md):
  * The metric is a *vector* of dimensions (count, p50, p95, max, error_rate,
    per-tool breakdown), never collapsed into one opaque score.
  * Health distinguishes healthy / degraded / unhealthy / stale / not_measured
    instead of treating "no data" as "fine". No records in the window with a
    non-empty file => `stale` (we had data, it aged out); an absent/empty file
    => `not_measured` (never observed), never `healthy`.
  * Percentiles are *measured* facts about the window; absence is `known_absent`.

Always-on property: the body is wrapped with `@always_up`, which restarts it on
crash and links the loop's Space/Health into the graph. Launch it detached via
the `run` tool (detach=true) so it outlives the request and the MCP server.

Usage:
    python scripts/latency_rollup_loop.py --once          # single rollup, print
    python scripts/latency_rollup_loop.py --interval 30   # forever, every 30s
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from mind_node_runtime.always_up import always_up  # noqa: E402
from mind_node_runtime.config import Settings  # noqa: E402
from mind_node_runtime.graph import GraphStore  # noqa: E402

LATENCY_LOG = REPO_ROOT / "agent1-migration" / "response-times.jsonl"

LOOP_SPACE_ID = "space:l2:mcp:latency-rollup-loop-v0"
METRIC_NODE_ID = "metric:l2:mcp:response-latency-v0"
HEALTH_NODE_ID = "health:l2:mcp:response-latency-v0"
SERVER_SPACE_ID = "space:l2:mcp:nodes-as-code-server-v0"

# Explicit, inspectable health thresholds (milliseconds / ratio). A choice, not a
# magic constant buried in a branch: p95 at/under WARN is healthy, at/under CRIT
# is degraded, above is unhealthy; likewise the error-rate bands.
P95_WARN_MS = 250.0
P95_CRIT_MS = 1000.0
ERROR_RATE_WARN = 0.02
ERROR_RATE_CRIT = 0.10
# Lock-wait bands: queueing behind the global dispatch lock is the true server
# contention signal, judged on its own axis.
LOCK_WAIT_WARN_MS = 50.0
LOCK_WAIT_CRIT_MS = 500.0
# Tools whose latency is the *command's* runtime, not the server's health, so
# they are excluded from the Health verdict (still shown in the per-tool Metric).
# `run` (terminal_command_ref) executes arbitrary shell commands: an 18s `run` is
# a slow command, not a sick server. Excluding it keeps Health honest instead of
# permanently red. The exclusion is reported (health_basis.excluded_tools), never
# silent.
HEALTH_EXCLUDED_TOOLS = {"run"}

_HEALTH_ORDER = {"healthy": 0, "degraded": 1, "unhealthy": 2}


def _worst(*states: str) -> str:
    """Worst (most severe) of the given health states."""
    return max(states, key=lambda s: _HEALTH_ORDER.get(s, 0))


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted, non-empty list."""
    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(1, min(len(sorted_values), round(pct / 100.0 * len(sorted_values))))
    return sorted_values[rank - 1]


def _read_window(log_path: Path, window_seconds: float, now_epoch: float) -> dict[str, Any]:
    """Read the JSONL stream and keep only records inside the trailing window.

    Returns the parsed window plus the file's freshness so the caller can tell
    `stale` (data existed but aged out) from `not_measured` (no file / no data).
    """
    if not log_path.exists():
        return {"file_present": False, "records": [], "total_lines": 0, "newest_epoch": None}

    records: list[dict[str, Any]] = []
    total = 0
    newest_epoch: float | None = None
    cutoff = now_epoch - window_seconds
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts")
            try:
                epoch = datetime.fromisoformat(ts).timestamp() if ts else None
            except (TypeError, ValueError):
                epoch = None
            if epoch is not None and (newest_epoch is None or epoch > newest_epoch):
                newest_epoch = epoch
            if epoch is not None and epoch >= cutoff:
                records.append(rec)
    return {"file_present": True, "records": records, "total_lines": total,
            "newest_epoch": newest_epoch}


def compute_rollup(log_path: Path, window_seconds: float, now_epoch: float) -> dict[str, Any]:
    """Pure aggregation: window -> metric vector + health verdict. No graph I/O."""
    window = _read_window(log_path, window_seconds, now_epoch)
    records = window["records"]

    if not records:
        if not window["file_present"] or window["total_lines"] == 0:
            info, health = "not_measured", "not_measured"
            observed = "no response-time records have ever been written"
        else:
            info, health = "known_absent", "stale"
            age = None if window["newest_epoch"] is None else round(now_epoch - window["newest_epoch"], 1)
            observed = f"no calls in the last {int(window_seconds)}s (newest record is {age}s old)"
        return {
            "information_status": info, "health_status": health,
            "window_seconds": window_seconds, "sample_count": 0,
            "observed": observed, "dimensions": {}, "per_tool": {},
        }

    latencies = sorted(float(r.get("total_ms") or 0.0) for r in records)
    errors = sum(1 for r in records if r.get("ok") is False)
    n = len(latencies)
    error_rate = round(errors / n, 4)
    p50 = round(_percentile(latencies, 50), 2)
    p95 = round(_percentile(latencies, 95), 2)
    p99 = round(_percentile(latencies, 99), 2)
    dimensions = {
        "count": n, "errors": errors, "error_rate": error_rate,
        "min_ms": round(latencies[0], 2), "p50_ms": p50, "p95_ms": p95,
        "p99_ms": p99, "max_ms": round(latencies[-1], 2),
        "mean_ms": round(sum(latencies) / n, 2),
    }

    # Lock-wait dimension (queueing behind the global dispatch lock), kept as its
    # own axis — never folded into total latency. Only records that actually took
    # a timed lock carry it; a null lock_wait means "no timed lock", not zero, so
    # it is excluded rather than counted as 0 (would understate contention).
    lock_waits = sorted(float(r["lock_wait_ms"]) for r in records
                        if r.get("lock_wait_ms") is not None)
    if lock_waits:
        dimensions["lock_wait_samples"] = len(lock_waits)
        dimensions["lock_wait_p95_ms"] = round(_percentile(lock_waits, 95), 2)
        dimensions["lock_wait_max_ms"] = round(lock_waits[-1], 2)
    else:
        dimensions["lock_wait_samples"] = 0

    # Per-tool breakdown (vector, never collapsed): p95 + count + errors per tool.
    per_tool: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        key = r.get("tool") or (r.get("method") or "unknown")
        grouped.setdefault(str(key), []).append(r)
    for key, group in grouped.items():
        lats = sorted(float(g.get("total_ms") or 0.0) for g in group)
        errs = sum(1 for g in group if g.get("ok") is False)
        per_tool[key] = {"count": len(lats), "errors": errs,
                         "p95_ms": round(_percentile(lats, 95), 2),
                         "max_ms": round(lats[-1], 2)}

    # Health verdict — judged on server-owned work only: `run`/terminal commands
    # are excluded (their latency is the command's, not the server's), and lock
    # contention is a distinct axis. The verdict is the WORST of the latency band
    # and the lock-wait band. The exclusion and the numbers it used are reported
    # under `health_basis` so nothing is dropped silently.
    health_records = [r for r in records
                      if (r.get("tool") or "") not in HEALTH_EXCLUDED_TOOLS]
    excluded = n - len(health_records)

    latency_health = "healthy"
    h_p95 = h_err_rate = None
    if health_records:
        h_lat = sorted(float(r.get("total_ms") or 0.0) for r in health_records)
        h_errs = sum(1 for r in health_records if r.get("ok") is False)
        h_p95 = round(_percentile(h_lat, 95), 2)
        h_err_rate = round(h_errs / len(health_records), 4)
        if h_p95 <= P95_WARN_MS and h_err_rate <= ERROR_RATE_WARN:
            latency_health = "healthy"
        elif h_p95 <= P95_CRIT_MS and h_err_rate <= ERROR_RATE_CRIT:
            latency_health = "degraded"
        else:
            latency_health = "unhealthy"

    lw_p95 = dimensions.get("lock_wait_p95_ms")
    if lw_p95 is None:
        lock_health = "healthy"
    elif lw_p95 <= LOCK_WAIT_WARN_MS:
        lock_health = "healthy"
    elif lw_p95 <= LOCK_WAIT_CRIT_MS:
        lock_health = "degraded"
    else:
        lock_health = "unhealthy"

    if not health_records:
        # Only excluded (run) calls in the window: server-owned work not observed.
        health = "not_measured" if lw_p95 is None else lock_health
    else:
        health = _worst(latency_health, lock_health)

    dimensions["health_basis"] = {
        "excluded_tools": sorted(HEALTH_EXCLUDED_TOOLS),
        "excluded_count": excluded,
        "judged_count": len(health_records),
        "latency_p95_ms": h_p95, "latency_error_rate": h_err_rate,
        "latency_health": latency_health if health_records else "not_measured",
        "lock_wait_p95_ms": lw_p95, "lock_health": lock_health,
    }

    return {
        "information_status": "measured", "health_status": health,
        "window_seconds": window_seconds, "sample_count": n,
        "observed": f"{n} calls in {int(window_seconds)}s (health judged on "
                    f"{len(health_records)} non-run): server p95="
                    f"{h_p95}ms lock_p95={lw_p95}ms -> {health}; overall p95={p95}ms "
                    f"max={dimensions['max_ms']}ms err={error_rate}",
        "dimensions": dimensions, "per_tool": per_tool,
    }


def write_rollup(store: GraphStore, rollup: dict[str, Any], now_iso: str) -> None:
    """Persist ONE Metric node and ONE derived Health node, linked to the server
    loop. This is the loop's only graph write per interval."""
    store.write(
        """
        MERGE (metric:RuntimeNode {id:$metric_id})
        SET metric.node_type='thing', metric.type='metric',
            metric.name='Metric · MCP response latency (rolling window)',
            metric.information_status=$info,
            metric.window_seconds=$window_seconds,
            metric.sample_count=$sample_count,
            metric.dimensions_json=$dimensions_json,
            metric.per_tool_json=$per_tool_json,
            metric.observed=$observed,
            metric.status='active',
            metric.last_assessed_at=$now
        MERGE (health:RuntimeNode {id:$health_id})
        SET health.node_type='narrative', health.subtype='health',
            health.name='Health · MCP response latency',
            health.health_state=$health_status,
            health.status=CASE $health_status
                WHEN 'healthy' THEN 'healthy'
                WHEN 'degraded' THEN 'degraded'
                WHEN 'unhealthy' THEN 'degraded'
                ELSE 'unknown' END,
            health.information_status=$info,
            health.observed=$observed,
            health.last_assessed_at=$now
        MERGE (health)-[:DERIVED_FROM]->(metric)
        WITH metric, health
        OPTIONAL MATCH (loop:RuntimeNode {id:$loop_space_id})
        FOREACH (_ IN CASE WHEN loop IS NULL THEN [] ELSE [1] END |
            MERGE (loop)-[:PRODUCES_METRIC]->(metric)
            MERGE (loop)-[:PRODUCES_HEALTH]->(health))
        WITH metric, health
        OPTIONAL MATCH (srv:RuntimeNode {id:$server_space_id})
        FOREACH (_ IN CASE WHEN srv IS NULL THEN [] ELSE [1] END |
            MERGE (metric)-[:MEASURES]->(srv))
        RETURN metric.id
        """,
        {
            "metric_id": METRIC_NODE_ID, "health_id": HEALTH_NODE_ID,
            "loop_space_id": LOOP_SPACE_ID, "server_space_id": SERVER_SPACE_ID,
            "info": rollup["information_status"],
            "health_status": rollup["health_status"],
            "window_seconds": rollup["window_seconds"],
            "sample_count": rollup["sample_count"],
            "dimensions_json": json.dumps(rollup["dimensions"], ensure_ascii=False),
            "per_tool_json": json.dumps(rollup["per_tool"], ensure_ascii=False),
            "observed": rollup["observed"],
            "now": now_iso,
        },
    )


def _now() -> tuple[float, str]:
    dt = datetime.now(timezone.utc)
    return dt.timestamp(), dt.isoformat()


def run_rollup_once(store: GraphStore | None, window_seconds: float) -> dict[str, Any]:
    epoch, iso = _now()
    rollup = compute_rollup(LATENCY_LOG, window_seconds, epoch)
    if store is not None:
        write_rollup(store, rollup, iso)
    rollup["assessed_at"] = iso
    return rollup


def main() -> None:
    parser = argparse.ArgumentParser(description="Always-on MCP response-latency rollup loop")
    parser.add_argument("--interval", type=float, default=30.0,
                        help="seconds between rollups (ignored with --once)")
    parser.add_argument("--window", type=float, default=300.0,
                        help="trailing window in seconds to aggregate")
    parser.add_argument("--once", action="store_true", help="run a single rollup and exit")
    parser.add_argument("--no-graph", action="store_true",
                        help="compute and print only, do not write the graph")
    args = parser.parse_args()

    store = None if args.no_graph else GraphStore(Settings())

    if args.once:
        out = run_rollup_once(store, args.window)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    @always_up(space_id=LOOP_SPACE_ID)
    def loop() -> None:
        while True:
            out = run_rollup_once(store, args.window)
            print(json.dumps({"assessed_at": out["assessed_at"],
                              "health": out["health_status"],
                              "samples": out["sample_count"],
                              "observed": out["observed"]}, ensure_ascii=False), flush=True)
            time.sleep(args.interval)

    loop()


if __name__ == "__main__":
    main()
