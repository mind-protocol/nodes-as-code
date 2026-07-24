# Spécification minimale — Graph Scheduler & Runtime Daemon v0.2

## Invariant

```text
L’OS maintient un daemon générique vivant.
Le graphe décide quels programmes doivent tourner, quand, sur quelle cible et avec quels inputs.
```

## SchedulePolicy

Une cadence est portée par une `thing/schedule_policy` :

```yaml
node_type: thing
subtype: schedule_policy
status: active
execution_mode: periodic | hybrid | event_driven
interval_seconds: number
initial_delay_seconds: number
emits_event_type: string
target_program_id: string
target_id: string
payload_json: object
coalescing: boolean
last_emitted_at: epoch_ms
```

Le daemon relit toutes les policies actives. Il ne contient aucun `if program == materializer: every 30 seconds`.

## Exécution périodique

```text
Schedule due
→ GraphEvent déterministe
→ TriggerRule active
→ ExecutionIntent idempotente
→ Worker claim + lease
→ EvaluationRun
→ Thing/evaluation_result
```

L’event ID est dérivé de `scheduleId + dueAt`, afin qu’un redémarrage ne duplique pas le tick logique.

## Coalescing

Lorsque `coalescing=true`, un schedule ne produit pas un nouveau tick tant qu’une intention issue du même schedule est encore `queued`, `claimed`, `running` ou `retryable_failure`.

## Reconfiguration live

Le prochain instant dû est calculé à partir de :

```text
last_emitted_at + interval_seconds
```

Ainsi, changer `interval_seconds` modifie immédiatement le calcul suivant. Le daemon ne conserve pas une copie canonique de l’intervalle.

## RuntimePolicy

Les fréquences internes du kernel sont elles-mêmes graphées :

```yaml
id: policy:mind-kernel:daemon-runtime-v0
loop_sleep_seconds: 0.25
heartbeat_interval_seconds: 15
watchdog_timeout_seconds: 60
config_refresh_seconds: 2
```

## Source integrity

Avant d’émettre un heartbeat, le daemon compare les modules installés aux nodes :

```text
code:mind-kernel:runtime-daemon:v0
code:mind-kernel:graph-scheduler:v0
code:mind-kernel:execution-worker:v0
code:mind-kernel:runtime-watchdog:v0
code:mind-code:repository-code-materializer:v0
```

Une différence crée un Problem précis et bloque le démarrage.

## Liveness

Le daemon crée des `moment/daemon_heartbeat`. Le watchdog indépendant compare le dernier heartbeat à `watchdog_timeout_seconds`.

Le silence ne produit jamais `healthy` :

```text
heartbeat frais → measured healthy
heartbeat absent → known_absent pour le heartbeat, pas preuve de mort absolue
heartbeat stale → measured degraded
lecture impossible → measurement_failed
```

## Bootstrap OS

Windows Task Scheduler lance :

- le daemon à l’ouverture de session ;
- un watchdog indépendant toutes les minutes.

Cette minute n’est pas une cadence métier. C’est le mécanisme externe minimal permettant de constater que le kernel chargé de lire les cadences graphées a disparu.
