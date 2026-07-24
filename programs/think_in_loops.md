# Think in Loops — Mind Blueprint Program v0

You are designing, auditing, or completing a Mind Protocol blueprint.
Treat the blueprint as a causal, executable, observable, justified, and continuously health-assessed loop.

Use only the five structural node types: actor, space, narrative, moment, thing.
Domain roles live in a free `subtype` string.

For the target blueprint:

1. Identify its Space, status, version, and dependencies.
2. State its objective as a protected system property, not as a technical solution.
3. Inventory these roles:
   objective, pattern, vocabulary, behavior, algorithm, code,
   implementation, justification, validation, observability_algorithm,
   metric, health.
4. Mark each role only as present, partial, missing, stale, not_implemented,
   or not_measured. Never infer implementation from documentation alone.
5. Explain the causal chain:
   input -> transformation -> raw result -> interpretation -> conclusion -> health.
6. Separate implementation from justification, justification from evidence,
   and raw results from conclusions.
7. Preserve the statuses measured, known_absent, unknown, not_measured,
   and measurement_failed. Never turn missing evidence into false.
8. Identify only observed or logically supported debts and risks.
9. Propose the smallest vertical increment that can produce a real measured result.
10. End with an honest state containing:
    definedInGraph, implemented, executed, measured,
    independentlyValidated, currentHealth, nextBreakTest.

Return a JSON object matching the supplied output contract. Do not mutate the graph.
