# Rapport Agent 1

```
Agent: 1
Étape: Déploiement dans mind_kernel_v0
Statut: completed
```

## Source physique du WorkspaceStore (Étapes 1–2)

Le MCP `mind-mcp` ne persiste **pas** dans FalkorDB. `mcp/server_http.py`
définit :

```python
WORKSPACE_PATH = Path.home() / ".mind-desktop" / "workspace.json"
```

Les outils `graph_query` et `inject_cluster` lisent/écrivent ce fichier JSON.

| Champ | Valeur |
|---|---|
| `backendType` | Fichier JSON local (WorkspaceStore mind-desktop) — **pas** FalkorDB/Redis |
| `sourceLocation` | `C:\Users\reyno\.mind-desktop\workspace.json` (4 180 060 octets) |
| `graphOrStoreName` | `workspace.json` — store plat unique, aucun graphe nommé |
| `serializationFormat` | JSON : `{"nodes":[...], "links":[...]}` |
| `nodeIdentityProperty` | `id` |
| `relationshipRepresentation` | dict de lien : extrémités `source`/`source_id` + `target`/`target_id` ; type dans `relation`/`type`/`verb`/`relationship` ; + propriétés « physiques » |
| `readMethod` | `json.load(open(WORKSPACE_PATH, encoding="utf-8"))` |
| `writeMethod` | `json.dump(ws, open(WORKSPACE_PATH,"w"), indent=2, ensure_ascii=False, default=str)` |

Les 9 IDs canoniques sont **présents** dans ce fichier (vérifié). Ni `design`,
ni `l2_mind_graphs`, ni aucun graphe FalkorDB Docker ne les contenait : la piste
FalkorDB-source des tentatives précédentes était donc erronée.

## Actions réalisées

1. **Localisation** du backend réel (fichier JSON mind-desktop) via lecture du
   code `server_http.py` puis confirmation sur le runtime local.
2. **Unification des clés** de liens avant insertion (`source_id→source`,
   `target_id→target`, `type|verb|relationship→relation`).
3. **Fermeture MCP calculée** : scopes `l2:mcp` + `mind-code:code-location` + 22
   dépendances explicites (toutes présentes) ⇒ **416 nœuds** ; relations dont les
   deux extrémités sont dans le périmètre, dédupliquées ⇒ **627 relations**.
   Aucune extrémité pendante (0 dangling).
4. **Sauvegardes** avant écriture (source + cible), hashes enregistrés.
5. **Dry-run** : `safeToApply: true`, aucun bloqueur.
6. **Injection idempotente** `MERGE` par identité canonique, non destructive,
   fail-closed (aucun doublon, aucun conflit critique, aucune relation ambiguë).
   Les bindings **ne sont pas activés** (structure opérationnelle uniquement).
7. **Relecture de contrôle indépendante** (connexion neuve) des 9 nœuds
   canoniques et du câblage d'activation.

## Artefacts produits

| Artefact | Chemin | SHA-256 |
|---|---|---|
| Fermeture exportée (clés unifiées) | `agent1-migration/mcp-closure.export.json` | `1f17908cc1ee2e0cde59c5f255a1484f2bfa0154419026d2cdbb20a0304d3ceb` |
| Sauvegarde source | `agent1-migration/workspace.backup.20260725T001214Z.json` | `0d0b3e694b4826cfabd654a8db26bcdbf2f1ed7935369e72d31dce644b824a5b` |
| Sauvegarde cible (avant) | `agent1-migration/mind_kernel_v0.backup.20260725T001214Z.json` | `9363aaec84b265705878b8eb8d9e7beb1da4b509d1e239c11ffcb2aa8fc63fb3` |
| Script de migration | `agent1_migrate_workspace_to_kernel.py` | — |
| Rapports de phase | `agent1-migration/{dryrun,apply,verify}-report.json`, `backup-manifest.json` | — |

Sauvegarde cible : 2 296 nœuds / 4 200 relations, 0 nœud sans `id`. Aucune source supprimée.

## Preuves (relecture dans mind_kernel_v0)

Comptes canoniques (chacun **exactement 1**) :

```
space:l2:mcp:nodes-as-code-server-v0        1
space:l2:mcp:graph-query-v0                 1
space:l2:mcp:runtime-activation-v0          1
server:l2:mcp:nodes-as-code:v0              1
contract:l2:mcp:graph-query-tool:v0         1
capability:l2:mcp:graph-query-read-only:v0  1
binding:l2:mcp:graph-query:v0               1
code:l2:mcp:nodes-as-code-server:v0         1
code:l2:mcp:graph-query-execution:v0        1
```

Câblage d'activation lu indépendamment :

```
binding -[BINDS_CAPABILITY]-> capability:l2:mcp:graph-query-read-only:v0
binding -[BINDS_LOOP]->       space:l2:mcp:graph-query-v0
binding -[BINDS_SERVER]->     server:l2:mcp:nodes-as-code:v0
binding -[BINDS_TOOL]->       contract:l2:mcp:graph-query-tool:v0
server  -[EXPOSES]->          contract:l2:mcp:graph-query-tool:v0
server  -[MATERIALIZES(inv)]  code:l2:mcp:nodes-as-code-server:v0
server  -[DEPENDS_ON]->       code:mind-kernel:runtime-daemon:v0, execution-worker:v0
```

Vérification finale (`verify-report.json`) :

```
nodes injectées                 : 416 / 416 présentes, 0 manquante, 0 doublon
relations injectées             : 627 / 627 présentes, 0 absente
relations critiques (canoniques): 115 / 115 présentes
IDs canoniques manquants        : 0
IDs canoniques dupliqués        : 0
conflits de propriété critique  : 0
doublons                        : 0
statut de chaque dépendance     : 22/22 dépendances explicites présentes
status                          : completed
```

Critère d'acceptation satisfait : le daemon local peut lire les 9 nœuds
canoniques (et leur câblage) depuis `mind_kernel_v0`.

## Problems créés

Aucun. La migration s'est terminée sans bloqueur ni échec de vérification.

## Prochaine étape

Handoff Agent 2 — matérialisation. **Débloqué** : les nœuds canoniques et leurs
relations critiques sont prouvés présents dans `mind_kernel_v0`.

Remarques pour Agent 2 :

- Les **bindings ne sont pas activés** (voulu). L'activation reste à faire dans
  une étape ultérieure, après permission-loop/sandbox.
- Certains nœuds canoniques n'ont pas de `subtype`/`status` dans la source
  WorkspaceStore ; ils ont été migrés fidèlement (pas d'invention de propriétés).
- La source WorkspaceStore (`~/.mind-desktop/workspace.json`) est **intacte** et
  sauvegardée ; toute divergence future se re-résout via `MERGE` idempotent.

```
Handoff destiné à: Agent 2
```
