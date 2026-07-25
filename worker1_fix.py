from falkordb import FalkorDB
g=FalkorDB(host="127.0.0.1",port=6379).select_graph("mind_kernel_v0")
queries=[
"""MATCH (s {id:'space:mind-runtime:stimulate-v0'}),(p {id:'space:mind-runtime:propagate-v0'})
OPTIONAL MATCH (s)-[r1:CONSUMES_OUTPUT_OF]->(p) DELETE r1
WITH s,p OPTIONAL MATCH (p)-[r2:PRECEDES]->(s) DELETE r2
WITH s,p OPTIONAL MATCH (s)-[r3:DEPENDS_ON]->(p) DELETE r3
WITH s,p OPTIONAL MATCH (p)-[r4:DEPENDS_ON]->(s) DELETE r4
WITH s,p MERGE (s)-[:PRECEDES]->(p) MERGE (p)-[:CONSUMES_OUTPUT_OF]->(s)""",
"""MATCH (s {id:'space:mind-runtime:stimulate-v0'}) OPTIONAL MATCH (s)-[r:DEPENDS_ON]->(m)
WHERE m.id STARTS WITH 'space:l2:mcp:' DELETE r""",
"""MATCH (p {id:'space:mind-runtime:propagate-v0'}) OPTIONAL MATCH (p)-[r:DEPENDS_ON]->(m)
WHERE m.id STARTS WITH 'space:l2:mcp:' DELETE r"""
]
for x in queries:g.query(x)
print("fixed")
