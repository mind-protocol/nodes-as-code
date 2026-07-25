"""
Always-Up Loop · Ollama DeepSeek-R1 14B Resident Model.

Materialized runtime artifact for the loop:

    space:l2:ollama:deepseek-r1-14b-loop-v0

Objective
    Keep `ollama run deepseek-r1:14b` continuously alive so the local
    DeepSeek-R1 14B model stays resident and responsive.

Mechanism
    The worker function is wrapped by the `@always_up` decorator loop
    (space:l2:mcp:stream-logger-decorator-v0). `always_up` runs the worker
    inside a supervised restart loop: on any exception it logs the crash to
    the graph error stream, sets health_status to 0, creates an incident
    task, backs off, then restarts. The worker therefore RAISES when the
    subprocess exits so the decorator restarts it — a clean normal return
    would end the supervision loop, which is not what "always up" means.

Epistemic discipline
    A running subprocess is NOT proof the model answers. The observer
    (`observe_deepseek_health`) probes the Ollama API independently and
    reports explicit status: observed / measurement_failed / known_absent /
    unknown. Missing evidence is never converted into success.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .always_up import always_up

# --------------------------------------------------------------------------- #
# Graph identifiers (must match ollama_deepseek_loop_seed.py)                  #
# --------------------------------------------------------------------------- #
LOOP_SPACE_ID = "space:l2:ollama:deepseek-r1-14b-loop-v0"
CODE_NODE_ID = "code:l2:ollama:deepseek-r1-14b-runner:v0"
OBSERVER_NODE_ID = "code:l2:ollama:deepseek-r1-14b-observer:v0"
HEALTH_NODE_ID = "health:l2:ollama:deepseek-r1-14b"

# --------------------------------------------------------------------------- #
# Configuration (env-overridable, faithful default to the requested command)  #
# --------------------------------------------------------------------------- #
DEFAULT_MODEL = os.getenv("OLLAMA_DEEPSEEK_MODEL", "deepseek-r1:14b")
DEFAULT_COMMAND = os.getenv("OLLAMA_DEEPSEEK_COMMAND", f"ollama run {DEFAULT_MODEL}")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
BACKOFF_SECONDS = float(os.getenv("OLLAMA_DEEPSEEK_BACKOFF_SECONDS", "3.0"))
HEARTBEAT_SECONDS = float(os.getenv("OLLAMA_DEEPSEEK_HEARTBEAT_SECONDS", "15.0"))


class OllamaProcessExited(RuntimeError):
    """Raised when the `ollama run` subprocess exits, to trigger @always_up restart."""


def _command_argv(command: str = DEFAULT_COMMAND) -> List[str]:
    """Split the configured command string into an argv list, cross-platform."""
    return shlex.split(command, posix=(os.name != "nt"))


def _graph_store() -> Any:
    """Best-effort GraphStore; returns None if the graph runtime is unavailable."""
    try:
        from .config import Settings
        from .graph import GraphStore

        return GraphStore(Settings())
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[ollama-deepseek-loop] Graph unavailable for health writes: {exc}", file=sys.stderr)
        return None


# Observer status -> (health_status, derived health state) — fresh evidence only.
_HEALTH_MAP = {
    "observed": (1, "healthy"),
    "known_absent": (0, "degraded"),
    "measurement_failed": (0, "measurement_failed"),
}


def _update_health_node(store: Any, observation: Dict[str, Any]) -> None:
    """Write live Health derived strictly from the Observer's fresh probe."""
    if store is None:
        return
    info = observation.get("information_status", "unknown")
    health_status, derived = _HEALTH_MAP.get(info, (0, "unknown"))
    try:
        store.write(
            """
            MERGE (h:RuntimeNode {id:$id})
            SET h.node_type='thing',
                h.subtype='health',
                h.name='Health · DeepSeek-R1 14B Loop',
                h.states='healthy | degraded | stale | unknown | not_measured | measurement_failed',
                h.health_status=$hs,
                h.derived_state=$derived,
                h.information_status=$info,
                h.evidence=$reason,
                h.last_probe_at=$ts,
                h.status='active'
            """,
            {
                "id": HEALTH_NODE_ID,
                "hs": health_status,
                "derived": derived,
                "info": info,
                "reason": observation.get("reason", ""),
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[ollama-deepseek-loop] Failed to write health node: {exc}", file=sys.stderr)


def _heartbeat_until_process_dies(
    process: "subprocess.Popen[Any]",
    store: Any,
    model: str,
    interval: float = HEARTBEAT_SECONDS,
) -> None:
    """Probe the model independently on each tick and refresh Health in the graph.

    Returns only when the subprocess has died (so the caller can raise and let
    @always_up restart it). While the process lives, Health is kept fresh from
    real Observer evidence — never from the mere existence of the process.
    """
    while process.poll() is None:
        observation = observe_deepseek_health(model=model)
        _update_health_node(store, observation)
        state = _HEALTH_MAP.get(observation.get("information_status"), (0, "unknown"))[1]
        print(
            f"[ollama-deepseek-loop] heartbeat: {state} ({observation.get('reason', '')})",
            file=sys.stderr,
        )
        time.sleep(interval)


def _ensure_model_pulled(store: Any, model: str = DEFAULT_MODEL) -> None:
    """Pull the model if the independent probe reports it absent.

    `ollama run` does not reliably pull when stdin is a pipe (non-TTY), so the
    loop makes the pull explicit and blocking. Progress streams to stderr. A
    failed pull raises OllamaProcessExited so @always_up retries (resumable).
    """
    observation = observe_deepseek_health(model=model)
    if observation.get("information_status") == "observed":
        return

    _update_health_node(store, observation)  # degraded / measurement_failed while acquiring
    print(f"[ollama-deepseek-loop] Model {model!r} absent -> pulling…", file=sys.stderr)
    try:
        completed = subprocess.run(["ollama", "pull", model])
    except FileNotFoundError as exc:
        raise OllamaProcessExited(f"'ollama' executable not found while pulling {model!r}: {exc}") from exc
    if completed.returncode != 0:
        raise OllamaProcessExited(
            f"`ollama pull {model}` exited with {completed.returncode}; requesting restart."
        )


@always_up(space_id=LOOP_SPACE_ID, backoff_seconds=BACKOFF_SECONDS)
def run_deepseek_r1_14b(command: str = DEFAULT_COMMAND) -> None:
    """Supervised worker: make `deepseek-r1:14b` resident and healthy, automatically.

    1. Ensure the model is present (explicit `ollama pull` if the probe says absent).
    2. Start `ollama run deepseek-r1:14b`, holding stdin OPEN so the session does
       not exit on EOF and the model stays resident.
    3. Heartbeat refreshes Health from an independent probe every tick.
    When the process eventually dies, raises OllamaProcessExited so the wrapping
    @always_up loop restarts it after a backoff — no manual action required.
    """
    store = _graph_store()
    _ensure_model_pulled(store, DEFAULT_MODEL)

    argv = _command_argv(command)
    print(f"[ollama-deepseek-loop] Starting resident model: {' '.join(argv)}", file=sys.stderr)

    try:
        # stdin=PIPE held open -> `ollama run` REPL never receives EOF -> the
        # process stays alive and the model stays resident.
        process = subprocess.Popen(argv, stdin=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise OllamaProcessExited(
            f"'ollama' executable not found while launching {argv!r}: {exc}"
        ) from exc

    try:
        _heartbeat_until_process_dies(process, store, DEFAULT_MODEL)
    finally:
        if process.poll() is None:
            process.terminate()

    return_code = process.poll()
    raise OllamaProcessExited(
        f"Subprocess {argv!r} exited with return code {return_code}; requesting restart."
    )


# --------------------------------------------------------------------------- #
# Independent Observer                                                         #
# --------------------------------------------------------------------------- #
def observe_deepseek_health(
    base_url: str = OLLAMA_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = 3.0,
) -> Dict[str, Any]:
    """Independently verify that the DeepSeek-R1 14B model is served and responsive.

    Does NOT trust the fact that a subprocess exists. Queries the Ollama API
    directly and returns an explicit epistemic status:

        - "observed"            : /api/tags reachable AND model tag present
        - "known_absent"        : API reachable but the model tag is missing
        - "measurement_failed"  : API unreachable / errored (Ollama offline?)

    A missing model is reported as known_absent, never as healthy.
    """
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            if resp.status != 200:
                return {
                    "information_status": "measurement_failed",
                    "healthy": False,
                    "reason": f"/api/tags returned HTTP {resp.status}",
                    "model": model,
                }
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {
            "information_status": "measurement_failed",
            "healthy": False,
            "reason": f"Ollama API unreachable: {exc!r}",
            "model": model,
        }

    tags = [m.get("name", "") for m in payload.get("models", [])]
    present = model in tags

    if present:
        return {
            "information_status": "observed",
            "healthy": True,
            "reason": "Model tag present in /api/tags",
            "model": model,
            "available_tags": tags,
        }
    return {
        "information_status": "known_absent",
        "healthy": False,
        "reason": f"Model {model!r} not present in served tags",
        "model": model,
        "available_tags": tags,
    }


def main() -> None:
    """Entrypoint: start the always-up DeepSeek-R1 14B loop, or observe it."""
    if "--observe" in sys.argv:
        result = observe_deepseek_health()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result.get("healthy") else 1)

    run_deepseek_r1_14b()


if __name__ == "__main__":
    main()
