from falkordb import FalkorDB
g=FalkorDB(host="127.0.0.1",port=6379).select_graph("mind_kernel_v0")
g.query("""MATCH (s {id:'space:mind-runtime:stimulate-v0'}),(p {id:'space:mind-runtime:propagate-v0'})
OPTIONAL MATCH (s)-[r:PRECEDES|CONSUMES_OUTPUT_OF|DEPENDS_ON]-(p)
DELETE r
WITH s,p
MERGE (s)-[:PRECEDES]->(p)
MERGE (p)-[:CONSUMES_OUTPUT_OF]->(s)""")
print("reset")
