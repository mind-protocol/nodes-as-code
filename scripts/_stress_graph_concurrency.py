"""Concurrency safety gate for the lock removal.

Hammers a SINGLE shared GraphStore (exactly how McpServer shares self.rw across
HTTP request threads) from many threads doing interleaved write+readback, with NO
external lock. With the pre-change single shared connection this corrupts the redis
protocol stream (exceptions / wrong rows). With per-thread connections it must be
clean: zero exceptions and every readback returns exactly what that thread wrote.

Exit 0 = safe to run the MCP server without the global dispatch lock.
"""
from __future__ import annotations

import sys
import threading

sys.path.insert(0, "src")
from mind_node_runtime.config import Settings  # noqa: E402
from mind_node_runtime.graph import GraphStore  # noqa: E402

N_THREADS = 16
N_ITERS = 40
PREFIX = "moment:l2:mcp:_stress_concurrency"

store = GraphStore(Settings())  # ONE shared instance, like the server's self.rw
errors: list[str] = []
mismatches: list[str] = []
ok_count = 0
_count_lock = threading.Lock()  # guards test bookkeeping only, NOT graph access


def worker(tid: int) -> None:
    global ok_count
    for i in range(N_ITERS):
        nid = f"{PREFIX}:{tid}-{i}"
        val = f"v-{tid}-{i}"
        try:
            # Write (uses this thread's own connection, no external lock)
            store.write(
                "MERGE (n:RuntimeNode {id:$id}) "
                "SET n.node_type='moment', n.subtype='stress', n.probe_value=$val",
                {"id": nid, "val": val},
            )
            # Read it back and also run a concurrent scan read to force contention
            rows = store.read("MATCH (n {id:$id}) RETURN n.probe_value", {"id": nid})
            store.read(
                "MATCH (n) WHERE n.subtype='stress' RETURN count(n)", {}
            )
            got = rows[0][0] if rows else None
            if got != val:
                with _count_lock:
                    mismatches.append(f"{nid}: wrote {val!r} read {got!r}")
            else:
                with _count_lock:
                    ok_count += 1
        except Exception as exc:  # any protocol corruption surfaces here
            with _count_lock:
                errors.append(f"{nid}: {type(exc).__name__}: {exc}")


def main() -> None:
    threads = [threading.Thread(target=worker, args=(t,), name=f"stress-{t}")
               for t in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = N_THREADS * N_ITERS
    print(f"threads={N_THREADS} iters={N_ITERS} total_ops={total}")
    print(f"ok_readbacks={ok_count} mismatches={len(mismatches)} errors={len(errors)}")
    for m in mismatches[:10]:
        print("  MISMATCH:", m)
    for e in errors[:10]:
        print("  ERROR:", e)

    # Cleanup: remove the stress nodes so the graph is left as found.
    try:
        store.write("MATCH (n) WHERE n.subtype='stress' DETACH DELETE n", {})
        print("cleanup: stress nodes deleted")
    except Exception as exc:
        print("cleanup FAILED:", exc)

    ok = (ok_count == total and not mismatches and not errors)
    print("RESULT:", "PASS (safe without lock)" if ok else "FAIL (do NOT remove lock)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
