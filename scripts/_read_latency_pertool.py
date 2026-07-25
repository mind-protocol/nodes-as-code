import sys, json
sys.path.insert(0, "src")
from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore

s = GraphStore(Settings())
r = s.read(
    "MATCH (n {id:'metric:l2:mcp:response-latency-v0'}) "
    "RETURN n.dimensions_json, n.per_tool_json, n.observed, n.last_assessed_at"
)
if not r:
    print("metric ABSENT"); sys.exit(0)
dims, per_tool, observed, ts = r[0]
print("assessed_at:", ts)
print("observed   :", observed)
print("\n=== overall dimensions ===")
print(json.dumps(json.loads(dims), indent=2))
print("\n=== per-tool (sorted by p95 desc) ===")
pt = json.loads(per_tool)
rows = sorted(pt.items(), key=lambda kv: kv[1].get("p95_ms", 0), reverse=True)
print(f"{'tool/method':<28} {'count':>6} {'errors':>6} {'p95_ms':>10} {'max_ms':>10}")
for name, d in rows:
    print(f"{name:<28} {d.get('count',0):>6} {d.get('errors',0):>6} "
          f"{d.get('p95_ms',0):>10} {d.get('max_ms',0):>10}")
