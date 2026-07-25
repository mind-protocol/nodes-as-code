from falkordb import FalkorDB
g=FalkorDB(host="127.0.0.1",port=6379).select_graph("mind_kernel_v0")
qs=[
"""MATCH (s {id:'space:mind-runtime:stimulate-v0'}),(p {id:'space:mind-runtime:propagate-v0'})
RETURN exists((s)-[:PRECEDES]->(p)),exists((p)-[:PRECEDES]->(s)),exists((s)-[:CONSUMES_OUTPUT_OF]->(p)),exists((p)-[:CONSUMES_OUTPUT_OF]->(s))""",
"""MATCH (n) WHERE n.id IN ['space:mind-runtime:l1-cognitive-cycle-v0','changeset:mind-runtime:l1-cognitive-cycle-worker1-v0'] RETURN n.id,count(n)""",
"""MATCH (s {id:'space:mind-runtime:stimulate-v0'}) OPTIONAL MATCH (s)-[r:DEPENDS_ON]->(m) WHERE m.id STARTS WITH 'space:l2:mcp:' RETURN count(r)""",
"""MATCH (p {id:'space:mind-runtime:propagate-v0'}) OPTIONAL MATCH (p)-[r:DEPENDS_ON]->(m) WHERE m.id STARTS WITH 'space:l2:mcp:' RETURN count(r)"""
]
for q in qs: print(g.query(q).result_set)
