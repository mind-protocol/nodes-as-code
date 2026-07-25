from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore
s=GraphStore(Settings(graph_name='mind_kernel_v0'))
cs='changeset:mind-runtime:worker2-v0'
rows=[
('space:mind-runtime:l1-membrane-admission-v0','mind_node_runtime.talk:TalkMembrane'),
('space:mind-perception:l1-percept-construction-v0','mind_node_runtime.brain.perception:PerceptionEngine'),
('space:mind-runtime:l1-metabolism-v0','mind_node_runtime.brain.metabolism:MetabolismEngine'),
('space:mind-affect:l1-affective-need-state-v0','mind_node_runtime.brain.affect:AffectEngine')]
s.write("MERGE (c:RuntimeNode {id:$id}) SET c.node_type='thing',c.subtype='changeset',c.status='applied',c.source_ref='user:implemente'",{"id":cs})
for id,entry in rows:
 p={'id':id,'entry':entry,'cs':cs}
 s.write("MERGE (x:RuntimeNode {id:$id}) SET x.node_type='space',x.subtype='ontology_module',x.status='implemented',x.contract_kind='self_verifying_loop',x.worker='2' MERGE (m:RuntimeNode {id:'space:mind-meta:self-verifying-loop-v0'}) MERGE (x)-[:INSTANCE_OF]->(m) WITH x MATCH (c:RuntimeNode {id:$cs}) MERGE (c)-[:APPLIES_TO]->(x)",p)
 for kind,rel,typ in [('objective','HAS_OBJECTIVE','narrative'),('algorithm','HAS_ALGORITHM','narrative'),('behavior','HAS_BEHAVIOR','narrative'),('implementation','HAS_IMPLEMENTATION','narrative'),('trigger','TRIGGERED_BY','thing'),('metric','MEASURED_BY','thing'),('observer','OBSERVED_BY','thing'),('health','HAS_HEALTH','narrative'),('validation','VALIDATED_BY','narrative')]:
  n='worker2:'+kind+':'+id.replace('space:','').replace(':','-')
  s.write("MATCH (x:RuntimeNode {id:$id}) MERGE (n:RuntimeNode {id:$n}) SET n.node_type=$typ,n.subtype=$kind,n.name=$kind+' Worker 2',n.content='provenance preserved; epistemic status explicit; no absent value becomes zero; no diagnosis' MERGE (x)-[r:"+rel+"]->(n)",{'id':id,'n':n,'typ':typ,'kind':kind})
 s.write("MATCH (x:RuntimeNode {id:$id}) MERGE (d:RuntimeNode {id:$n}) SET d.node_type='thing',d.subtype='code_definition',d.language='python',d.authority_mode='graph_source',d.version='0.1.0',d.entrypoint=$entry,d.status='active' MERGE (x)-[:HAS_CODE_DEFINITION]->(d)",{'id':id,'n':'code:worker2:'+id.replace('space:','').replace(':','-')+':v0','entry':entry})
for id,name,fields in [
('schema:mind-runtime:percept-bundle:v0','PerceptBundle','percepts,source_refs,epistemic_status'),
('schema:mind-runtime:human-state-frame:v0','HumanStateFrame','capacity,fatigue,sleep,pain,hunger,hydration,heat,substances,cognitive_load,urgency,freshness'),
('schema:mind-runtime:affective-need-state:v0','AffectiveNeedState','textual_observations,affective_hypotheses,consolidated_state,evidence')]:
 s.write("MERGE (n:RuntimeNode {id:$id}) SET n.node_type='thing',n.subtype='type_definition',n.name=$name,n.fields=$fields,n.epistemic_statuses='observed,inferred,unknown,not_measured,measurement_failed',n.status='active'",{'id':id,'name':name,'fields':fields})
s.write("MATCH (m:RuntimeNode {id:'space:mind-runtime:l1-membrane-admission-v0'}),(p:RuntimeNode {id:'space:mind-perception:l1-percept-construction-v0'}),(h:RuntimeNode {id:'space:mind-runtime:l1-metabolism-v0'}),(a:RuntimeNode {id:'space:mind-affect:l1-affective-need-state-v0'}) MERGE (m)-[:PRECEDES]->(p) MERGE (p)-[:CONSUMES_OUTPUT_OF]->(m) MERGE (p)-[:PRECEDES]->(h) MERGE (h)-[:CONSUMES_OUTPUT_OF]->(p) MERGE (h)-[:PRECEDES]->(a) MERGE (a)-[:CONSUMES_OUTPUT_OF]->(p) MERGE (a)-[:CONSUMES_OUTPUT_OF]->(h)")
print(cs)
