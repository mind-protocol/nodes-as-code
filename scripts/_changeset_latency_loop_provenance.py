"""ChangeSet: graph-first provenance for the response-latency observability loop.

Records, into mind_kernel_v0, the causal chain for the loop whose runtime code
already exists (always_up.flux_latency + scripts/latency_rollup_loop.py):

    objective -> pattern -> behavior -> algorithm
              -> code (decorator + rollup) -> implementation
              -> justification -> observer -> metric -> health

plus a provenance Moment (attributed to an Actor, concerning the touched files).
Idempotent: every node/relation is MERGEd by id. Bounded to the latency loop
subgraph — it never rewrites unrelated state. Run with --readback to print the
resolved chain after applying.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from mind_node_runtime.config import Settings  # noqa: E402
from mind_node_runtime.graph import GraphStore  # noqa: E402
from mind_node_runtime.hashing import sha256_text  # noqa: E402

LOOP = "space:l2:mcp:latency-rollup-loop-v0"
DECO_SPACE = "space:l2:mcp:flux-latency-decorator-v0"
SERVER = "space:l2:mcp:nodes-as-code-server-v0"

OBJECTIVE = "objective:l2:mcp:response-latency-observability"
PATTERN = "pattern:l2:mcp:flux-decorator-plus-rollup"
BEHAVIOR_DECO = "behavior:l2:mcp:response-latency-capture"
BEHAVIOR_ROLLUP = "behavior:l2:mcp:response-latency-rollup"
ALGORITHM = "algorithm:l2:mcp:latency-rollup"
CODE_DECO = "code:l2:mcp:flux-latency-decorator:v0"
CODE_ROLLUP = "code:l2:mcp:latency-rollup-loop:v0"
IMPLEMENTATION = "implementation:l2:mcp:latency-rollup-loop-v0"
JUSTIFICATION = "narrative:l2:mcp:latency-loop-justification"
OBSERVER = "observer:l2:mcp:latency-rollup"
METRIC = "metric:l2:mcp:response-latency-v0"
HEALTH = "health:l2:mcp:response-latency-v0"
VOCABULARY = "vocabulary:l2:mcp:response-latency"
VALIDATION = "validation:l2:mcp:latency-rollup"
OBSERVER_VALIDATION = "validation:l2:mcp:latency-observer"
ACTOR = "actor:agent:claude-code"

ALWAYS_UP = REPO_ROOT / "src" / "mind_node_runtime" / "always_up.py"
ROLLUP_FILE = REPO_ROOT / "scripts" / "latency_rollup_loop.py"


def apply(store: GraphStore) -> str:
    now = datetime.now(timezone.utc).isoformat()
    deco_hash = sha256_text(ALWAYS_UP.read_text(encoding="utf-8"))
    rollup_hash = sha256_text(ROLLUP_FILE.read_text(encoding="utf-8"))
    moment_id = f"moment:l2:mcp:latency-loop-materialized-{int(datetime.now(timezone.utc).timestamp())}"

    # All human text is passed via PARAMETERS, never embedded in the Cypher
    # literal: FalkorDB has no SQL-style '' escaping, so apostrophes ("loop's")
    # in an inline literal are a parse error. Parameters sidestep escaping.

    # 1. The loop Space itself (created here if the loop has not yet run; the
    #    @always_up decorator also auto-links it on first execution).
    store.write(
        """
        MERGE (l:RuntimeNode {id:$loop})
        SET l.node_type='space', l.contractKind='self_verifying_loop',
            l.loopType='flux', l.name=$name, l.promise=$promise,
            l.status='active', l.updated_at=$now
        """,
        {"loop": LOOP, "now": now,
         "name": "Loop · MCP response-latency observability v0",
         "promise": "Every dispatched call's response time is measured and rolled "
                    "up into a fresh, honest Metric/Health without taxing the hot path."},
    )

    # 2. Role nodes of the loop.
    store.write(
        """
        MERGE (o:RuntimeNode {id:$objective})
        SET o.node_type='narrative', o.subtype='objective', o.name=$o_name,
            o.content=$o_content, o.success_condition=$o_success,
            o.information_status='measured', o.status='active', o.updated_at=$now
        MERGE (p:RuntimeNode {id:$pattern})
        SET p.node_type='narrative', p.subtype='pattern', p.name=$p_name,
            p.content=$p_content,
            p.information_status='measured', p.status='active', p.updated_at=$now
        MERGE (a:RuntimeNode {id:$algorithm})
        SET a.node_type='narrative', a.subtype='algorithm', a.name=$a_name,
            a.content=$a_content,
            a.information_status='measured', a.status='active', a.updated_at=$now
        """,
        {"objective": OBJECTIVE, "pattern": PATTERN, "algorithm": ALGORITHM, "now": now,
         "o_name": "Objective · Observe MCP response latency honestly",
         "o_content": "Preserve an observable, evidence-backed view of MCP JSON-RPC "
                      "response times (per call and aggregated) so latency regressions "
                      "and lock contention are detected, without the measurement itself "
                      "adding graph writes or lock contention to the measured path.",
         "o_success": "A Metric with fresh (non-stale) measured p50/p95/max/error_rate "
                      "exists whenever calls have occurred in the window; when none have, "
                      "Health reads stale/not_measured, never healthy.",
         "p_name": "Pattern · Cheap in-path flux decorator + out-of-path rollup loop",
         "p_content": "Capture is a decorator on the request flow that appends one JSONL "
                      "line per call (never a per-call graph write). Aggregation is a "
                      "separate always-on loop that folds a trailing window into a single "
                      "graph Metric/Health per interval.",
         "a_name": "Algorithm · Windowed latency rollup",
         "a_content": "Read JSONL; keep records with ts >= now-window; if none: "
                      "known_absent+stale (file had data) or not_measured (empty/absent); "
                      "else sort total_ms, compute count/errors/error_rate/min/p50/p95/p99/"
                      "max/mean plus per-tool p95/max; health = healthy if p95<=WARN and "
                      "err<=WARN, degraded if p95<=CRIT and err<=CRIT, else unhealthy. "
                      "Never invents defaults for missing evidence."},
    )

    store.write(
        """
        MERGE (bc:RuntimeNode {id:$behavior_deco})
        SET bc.node_type='narrative', bc.subtype='behavior', bc.name=$bc_name,
            bc.content=$bc_content,
            bc.information_status='measured', bc.status='active', bc.updated_at=$now
        MERGE (br:RuntimeNode {id:$behavior_rollup})
        SET br.node_type='narrative', br.subtype='behavior', br.name=$br_name,
            br.content=$br_content,
            br.information_status='measured', br.status='active', br.updated_at=$now
        """,
        {"behavior_deco": BEHAVIOR_DECO, "behavior_rollup": BEHAVIOR_ROLLUP, "now": now,
         "bc_name": "Behavior · Per-call response-time capture",
         "bc_content": "GIVEN a JSON-RPC call is dispatched by the MCP server WHEN dispatch "
                       "returns (result or error) THEN exactly one record {ts,method,tool,"
                       "total_ms,ok,information_status[,returncode,timed_out,error]} is "
                       "appended to the response-time stream. FORBIDDEN: altering the call "
                       "result, failing the call because logging failed, writing to the "
                       "graph per call, or logging transport notifications.",
         "br_name": "Behavior · Windowed rollup to Metric/Health",
         "br_content": "GIVEN the response-time stream WHEN the rollup loop ticks every "
                       "interval THEN one Metric (vector of dimensions + per-tool breakdown) "
                       "and one derived Health are written for the trailing window with "
                       "information_status in {measured,known_absent,not_measured}. "
                       "FORBIDDEN: reporting healthy when no fresh records exist; collapsing "
                       "dimensions into one opaque score."},
    )

    # 3. CodeDefinitions (source_path + symbol + file source_hash for provenance).
    store.write(
        """
        MERGE (cd:RuntimeNode {id:$code_deco})
        SET cd.node_type='thing', cd.type='code', cd.language='python', cd.name=$cd_name,
            cd.source_path='src/mind_node_runtime/always_up.py', cd.symbol='flux_latency',
            cd.source_hash=$deco_hash, cd.status='materialized', cd.updated_at=$now
        MERGE (cr:RuntimeNode {id:$code_rollup})
        SET cr.node_type='thing', cr.type='code', cr.language='python', cr.name=$cr_name,
            cr.source_path='scripts/latency_rollup_loop.py', cr.symbol='compute_rollup+write_rollup+main',
            cr.source_hash=$rollup_hash, cr.status='materialized', cr.updated_at=$now
        MERGE (impl:RuntimeNode {id:$impl})
        SET impl.node_type='thing', impl.type='implementation', impl.name=$impl_name,
            impl.realization_state='materialized_and_verified', impl.evidence=$impl_evidence,
            impl.information_status='measured', impl.status='active', impl.updated_at=$now
        """,
        {"code_deco": CODE_DECO, "code_rollup": CODE_ROLLUP, "impl": IMPLEMENTATION,
         "deco_hash": deco_hash, "rollup_hash": rollup_hash, "now": now,
         "cd_name": "CodeDefinition · flux_latency decorator v0",
         "cr_name": "CodeDefinition · latency rollup loop v0",
         "impl_name": "Implementation · latency rollup loop v0",
         "impl_evidence": "In-process dispatch probe wrote 3 JSONL records; rollup readback "
                          "confirmed Metric+Health nodes and DERIVED_FROM edge in mind_kernel_v0."},
    )

    # 4. Justification + Observer.
    store.write(
        """
        MERGE (j:RuntimeNode {id:$justification})
        SET j.node_type='narrative', j.subtype='justification', j.name=$j_name,
            j.content=$j_content,
            j.information_status='measured', j.status='active', j.updated_at=$now
        MERGE (obs:RuntimeNode {id:$observer})
        SET obs.node_type='thing', obs.type='observer', obs.name=$obs_name,
            obs.content=$obs_content,
            obs.information_status='measured', obs.status='active', obs.updated_at=$now
        """,
        {"justification": JUSTIFICATION, "observer": OBSERVER, "now": now,
         "j_name": "Justification · Why decorator+rollup over per-call graph write",
         "j_content": "A graph write per request would run under the server dispatch lock "
                      "and add latency and contention to the exact path being measured — "
                      "self-defeating. A disk JSONL append is ~microseconds and lock-free; a "
                      "single windowed rollup keeps graph writes bounded (one per interval) "
                      "while preserving epistemic honesty (measured percentiles, stale vs "
                      "not_measured). Rejected alternatives: (a) per-call graph Moment "
                      "(hot-path tax); (b) external HTTP prober only (misses in-process/"
                      "stdio calls and cannot see the true dispatch time).",
         "obs_name": "Observer · Independent latency evidence reader",
         "obs_content": "Reads the on-disk response-time stream (real evidence produced by "
                        "the request path), not the loop's own claims, and derives the "
                        "Metric/Health from it."},
    )

    # 4b. Vocabulary + Validation + Observer-validation (closes the loop to 12/12).
    store.write(
        """
        MERGE (v:RuntimeNode {id:$vocabulary})
        SET v.node_type='narrative', v.subtype='vocabulary', v.name=$v_name,
            v.content=$v_content,
            v.information_status='measured', v.status='active', v.updated_at=$now
        MERGE (val:RuntimeNode {id:$validation})
        SET val.node_type='thing', val.type='validation', val.name=$val_name,
            val.content=$val_content, val.cases_json=$val_cases,
            val.information_status='measured', val.status='active', val.updated_at=$now
        MERGE (ov:RuntimeNode {id:$observer_validation})
        SET ov.node_type='thing', ov.type='validation', ov.name=$ov_name,
            ov.content=$ov_content,
            ov.information_status='measured', ov.status='active', ov.updated_at=$now
        """,
        {"vocabulary": VOCABULARY, "validation": VALIDATION,
         "observer_validation": OBSERVER_VALIDATION, "now": now,
         "v_name": "Vocabulary · Response-latency terms",
         "v_content": "total_ms: end-to-end wall-clock of one dispatched JSON-RPC call. "
                      "p50/p95/p99_ms: nearest-rank percentiles over the window. "
                      "window: trailing seconds aggregated. measured: fresh calls observed. "
                      "known_absent: no calls in window though the stream had data. "
                      "stale: newest record older than the window. not_measured: stream "
                      "empty/absent. error_rate: fraction of calls with ok=false. "
                      "health_basis: the non-run subset + thresholds the Health verdict used. "
                      "excluded_tools: tools (run) whose latency is the command's, not the "
                      "server's, so excluded from Health.",
         "val_name": "Validation · Latency rollup fixtures",
         "val_content": "Fixtures challenging the algorithm's epistemic branches and the "
                        "concurrency-safety of the lock-free graph access. Each case states "
                        "input and expected classification/outcome.",
         "val_cases": json.dumps([
             {"case": "records_in_window", "given": "calls with ts within window",
              "expect_information_status": "measured", "expect_health": "healthy|degraded|unhealthy"},
             {"case": "data_aged_out", "given": "stream has data but none within window",
              "expect_information_status": "known_absent", "expect_health": "stale"},
             {"case": "empty_or_absent_stream", "given": "no file or zero records",
              "expect_information_status": "not_measured", "expect_health": "not_measured"},
             {"case": "run_excluded_from_health", "given": "slow run calls + fast graph calls",
              "expect": "health judged on non-run subset; run visible in per_tool only"},
             {"case": "concurrency_safe_without_lock",
              "given": "16 threads x 40 write+readback on one shared GraphStore, no external lock",
              "expect": "0 errors, 0 mismatches (scripts/_stress_graph_concurrency.py PASS)"},
         ], ensure_ascii=False),
         "ov_name": "Observer-validation · Missing evidence never becomes success",
         "ov_content": "Proves the observer converts absence into an explicit negative state, "
                       "never into health. Evidence: the stale case yields information_status "
                       "known_absent + health stale (not healthy); the empty case yields "
                       "not_measured (not healthy). Verified live: the loop reported stale with "
                       "'newest record is 111.2s old' and not_measured on an absent stream."},
    )

    # 5. Wire the loop chain (canonical relation names per mcp_server LOOP_ROLE_RELATIONS).
    store.write(
        """
        MATCH (l:RuntimeNode {id:$loop})
        MATCH (o {id:$objective}) MATCH (p {id:$pattern}) MATCH (a {id:$algorithm})
        MATCH (bc {id:$behavior_deco}) MATCH (br {id:$behavior_rollup})
        MATCH (cd {id:$code_deco}) MATCH (cr {id:$code_rollup})
        MATCH (impl {id:$impl}) MATCH (j {id:$justification}) MATCH (obs {id:$observer})
        MATCH (m {id:$metric}) MATCH (h {id:$health})
        MATCH (voc {id:$vocabulary}) MATCH (val {id:$validation}) MATCH (ov {id:$observer_validation})
        MERGE (l)-[:HAS_OBJECTIVE]->(o)
        MERGE (l)-[:USES_PATTERN]->(p)
        MERGE (l)-[:HAS_ALGORITHM]->(a)
        MERGE (l)-[:HAS_BEHAVIOR]->(bc)
        MERGE (l)-[:HAS_BEHAVIOR]->(br)
        MERGE (l)-[:HAS_CODE_DEFINITION]->(cd)
        MERGE (l)-[:HAS_CODE_DEFINITION]->(cr)
        MERGE (l)-[:HAS_IMPLEMENTATION]->(impl)
        MERGE (impl)-[:IMPLEMENTED_BY]->(cr)
        MERGE (l)-[:JUSTIFIED_BY]->(j)
        MERGE (l)-[:OBSERVED_BY]->(obs)
        MERGE (l)-[:MEASURED_BY]->(m)
        MERGE (l)-[:HAS_HEALTH]->(h)
        MERGE (obs)-[:PRODUCES_METRIC]->(m)
        MERGE (a)-[:REALIZED_BY]->(cr)
        MERGE (bc)-[:REALIZED_BY]->(cd)
        MERGE (l)-[:USES_VOCABULARY]->(voc)
        MERGE (l)-[:VALIDATED_BY]->(val)
        MERGE (obs)-[:VALIDATED_BY]->(ov)
        """,
        {"loop": LOOP, "objective": OBJECTIVE, "pattern": PATTERN, "algorithm": ALGORITHM,
         "behavior_deco": BEHAVIOR_DECO, "behavior_rollup": BEHAVIOR_ROLLUP,
         "code_deco": CODE_DECO, "code_rollup": CODE_ROLLUP, "impl": IMPLEMENTATION,
         "justification": JUSTIFICATION, "observer": OBSERVER, "metric": METRIC, "health": HEALTH,
         "vocabulary": VOCABULARY, "validation": VALIDATION,
         "observer_validation": OBSERVER_VALIDATION},
    )

    # 6. Link the decorator to the server loop it wraps (dispatch flow).
    store.write(
        """
        MATCH (cd {id:$code_deco})
        OPTIONAL MATCH (srv {id:$server})
        FOREACH (_ IN CASE WHEN srv IS NULL THEN [] ELSE [1] END |
            MERGE (cd)-[:WRAPS_FLOW]->(srv))
        """,
        {"code_deco": CODE_DECO, "server": SERVER},
    )

    # 7. Provenance Moment: attributed to an Actor, concerning the touched code.
    store.write(
        """
        MERGE (act:RuntimeNode {id:$actor})
        SET act.node_type='actor', act.subtype='agent_actor',
            act.name='Claude Code (authoring agent)', act.status='active', act.updated_at=$now
        MERGE (mo:RuntimeNode {id:$moment})
        SET mo.node_type='moment', mo.subtype='materialization',
            mo.name='Moment · Latency loop materialized + provenance recorded',
            mo.content='Added flux_latency decorator on dispatch, response-times.jsonl stream, and the always-on rollup loop; recorded the graph-first causal chain.',
            mo.information_status='measured', mo.status='observed', mo.created_at=$now
        WITH act, mo
        MATCH (l {id:$loop}) MATCH (cd {id:$code_deco}) MATCH (cr {id:$code_rollup})
        MERGE (mo)-[:CREATED_BY]->(act)
        MERGE (mo)-[:MATERIALIZES]->(l)
        MERGE (mo)-[:CONCERNS]->(cd)
        MERGE (mo)-[:CONCERNS]->(cr)
        """,
        {"actor": ACTOR, "moment": moment_id, "loop": LOOP,
         "code_deco": CODE_DECO, "code_rollup": CODE_ROLLUP, "now": now},
    )
    return moment_id


def readback(store: GraphStore) -> None:
    rows = store.read(
        """
        MATCH (l:RuntimeNode {id:$loop})-[r]->(n)
        RETURN type(r), n.id, n.node_type, coalesce(n.subtype, n.type)
        ORDER BY type(r), n.id
        """,
        {"loop": LOOP},
    )
    print(f"{LOOP} resolves to {len(rows)} role edges:")
    for rel, nid, ntype, sub in rows:
        print(f"  -[:{rel}]-> {nid}  ({ntype}/{sub})")
    prov = store.read(
        "MATCH (mo:RuntimeNode)-[:MATERIALIZES]->(l {id:$loop}) "
        "RETURN mo.id, mo.created_at ORDER BY mo.created_at DESC LIMIT 3",
        {"loop": LOOP},
    )
    print("provenance moments:", prov)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply latency-loop graph provenance")
    parser.add_argument("--readback", action="store_true")
    args = parser.parse_args()
    store = GraphStore(Settings())
    moment_id = apply(store)
    print("applied; provenance moment:", moment_id)
    if args.readback:
        readback(store)


if __name__ == "__main__":
    main()
