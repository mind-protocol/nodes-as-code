import sys
sys.path.insert(0, "src")
from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore

s = GraphStore(Settings())
r = s.read(
    "MATCH (n {id:'metric:l2:mcp:response-latency-v0'}) "
    "RETURN n.last_assessed_at, n.sample_count, n.information_status"
)
h = s.read(
    "MATCH (n {id:'health:l2:mcp:response-latency-v0'}) "
    "RETURN n.health_state, n.status"
)
print("metric:", r[0] if r else "ABSENT")
print("health:", h[0] if h else "ABSENT")
