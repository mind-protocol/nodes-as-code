# Mind Node-as-Code V1 — daemon graphé, sans API HTTP

Ce projet exécute des Nodes-as-Code uniquement après autorisation graphée :

```text
GraphEvent → TriggerRule → ExecutionIntent → EvaluationRun → Thing/evaluation_result
```

Le daemon physique reste volontairement petit. Il fournit une horloge, lit les `schedule_policy`, résout les événements, exécute les intentions, écrit les heartbeats et réconcilie les leases. Les programmes, cibles, cadences, modes d’exécution et payloads restent dans FalkorDB.

## Principe de cadence

L’intervalle est une propriété de la node `schedule_policy` :

```text
schedule:mind-code:periodic-code-materialization-v0
  status: active
  execution_mode: hybrid
  interval_seconds: 30
```

Modifier `interval_seconds` dans FalkorDB suffit. Le daemon relit les policies actives en continu ; aucun redémarrage n’est nécessaire.

Modes reconnus par le scheduler :

- `periodic` : émission selon `interval_seconds` ;
- `hybrid` : événements immédiats lorsqu’ils existent, plus réconciliation périodique ;
- `event_driven` : aucune émission temporelle par le scheduler.

Les programmes de service arbitraires restant vivants en subprocess ne sont pas encore activés. Le daemon lui-même est le runtime continu et sa liveness est vérifiée par heartbeat.

## Installation locale

```powershell
docker compose up -d

py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

python -m mind_node_runtime bootstrap --graph mind_kernel_v0
```

Le bootstrap crée notamment :

```text
code:mind-kernel:runtime-daemon:v0
code:mind-kernel:graph-scheduler:v0
code:mind-kernel:execution-worker:v0
code:mind-kernel:runtime-watchdog:v0
code:mind-code:repository-code-materializer:v0
policy:mind-kernel:daemon-runtime-v0
schedule:mind-code:periodic-code-materialization-v0
```

Les sources Python complètes sont stockées dans les nodes `thing/code`. Au démarrage, le daemon compare les hashes graphés aux modules installés et refuse de tourner en cas de divergence.

## Test manuel du daemon

Un tick complet :

```powershell
python -m mind_node_runtime daemon `
  --graph mind_kernel_v0 `
  --repo "." `
  --once
```

Exécution continue :

```powershell
python -m mind_node_runtime daemon `
  --graph mind_kernel_v0 `
  --repo "."
```

Après environ deux secondes, le schedule actif doit produire un événement, une intention, un run et une matérialisation sous :

```text
.mind/generated/code/
```

## Démarrage automatique Windows

Une seule installation est nécessaire :

```powershell
.\install_mind_runtime.ps1 `
  -Graph "mind_kernel_v0" `
  -Project (Get-Location).Path
```

Le script crée deux tâches Windows :

1. **Mind Node Runtime** : démarre le daemon à l’ouverture de session et le relance en cas d’arrêt ;
2. **Mind Node Runtime Watchdog** : vérifie chaque minute la fraîcheur du heartbeat graphé et redémarre la tâche si nécessaire.

Windows ne connaît aucune cadence métier. Il maintient seulement le kernel vivant. Les intervalles restent dans FalkorDB.

Désinstallation :

```powershell
.\uninstall_mind_runtime.ps1
```

## Heartbeat et watchdog

Le daemon écrit des `moment/daemon_heartbeat` selon :

```text
policy:mind-kernel:daemon-runtime-v0
  heartbeat_interval_seconds: 15
  watchdog_timeout_seconds: 60
  config_refresh_seconds: 2
  loop_sleep_seconds: 0.25
```

Vérification manuelle :

```powershell
python -m mind_node_runtime watchdog --graph mind_kernel_v0
```

Résultats possibles :

- `alive` : heartbeat frais ;
- `stale_or_absent` : Problem explicatif créé dans le graphe ;
- `measurement_failed` : FalkorDB ou l’observer n’a pas pu être lu.

## Modifier la cadence en direct

Dans FalkorDB :

```cypher
MATCH (s {id:'schedule:mind-code:periodic-code-materialization-v0'})
SET s.interval_seconds = 10.0
RETURN s.id, s.interval_seconds
```

Le prochain calcul utilise dix secondes sans redémarrer le daemon.

Désactiver le schedule :

```cypher
MATCH (s {id:'schedule:mind-code:periodic-code-materialization-v0'})
SET s.status = 'inactive'
```

Le réactiver :

```cypher
MATCH (s {id:'schedule:mind-code:periodic-code-materialization-v0'})
SET s.status = 'active', s.last_emitted_at = 0
```

## Matérialisation manuelle et résolution live

La commande directe reste disponible pour diagnostic :

```powershell
mind-code-materialize --graph mind_kernel_v0 --repo "." sync
```

Résolution d’un programme :

```powershell
mind-code-materialize `
  --graph mind_kernel_v0 `
  --repo "." `
  resolve `
  --program "code:mind-blueprints:think-in-loops-prompt:v0"
```

Le graphe reste l’autorité :

```text
Graphe → repo : autorisé
Repo → graphe : interdit
```

Une copie locale n’est utilisée que si son hash correspond au contenu actuel du graphe. Sinon, le runtime fetch la node et rafraîchit le cache.

## Déclencher manuellement un Node-as-Code

```powershell
python .\trigger_node_as_code.py `
  --graph "mind_kernel_v0" `
  --program "code:mind-blueprints:think-in-loops-prompt:v0" `
  --target "space:demo:blueprint-v0" `
  --mode complete `
  --inputs "{}" `
  --output ".\result.json"
```

La commande crée un événement ; elle n’appelle jamais directement le programme.

## Tests

```powershell
pip install -e .[dev]
pytest
```

La suite couvre notamment :

- décision de cadence depuis la schedule node ;
- reconfiguration de l’intervalle ;
- absence de polling pour `event_driven` ;
- bindings `$daemon.repo_root` ;
- matérialisation via un entrypoint enregistré ;
- cache local frais versus fetch live.

## Limites honnêtes

- FalkorDB ne possède pas de trigger post-écriture natif utilisé ici ; les mutations normales doivent produire leurs `GraphEvent`, et le sweep périodique ferme les trous éventuels ;
- la supervision de subprocess arbitraires en mode `continuous` n’est pas activée avant la Permission Loop, le sandbox et Node-as-Code Truth opérationnel ;
- le watchdog Windows est le bootstrap physique indépendant : un processus arrêté ne peut pas certifier lui-même son arrêt ;
- l’intégration FalkorDB réelle doit être testée sur la machine cible ; l’environnement de génération ne disposait pas de Docker.
