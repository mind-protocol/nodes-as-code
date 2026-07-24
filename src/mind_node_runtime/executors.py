from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from .scanner import build_blueprint_analysis


@dataclass(frozen=True)
class ExecutionOutput:
    value: dict[str, Any]
    executor_type: str


def execute_deterministic(target: dict[str, Any], neighbours: list[dict[str, Any]]) -> ExecutionOutput:
    return ExecutionOutput(
        value=build_blueprint_analysis(target, neighbours),
        executor_type="deterministic_blueprint_inventory_v0",
    )


def execute_ollama_cli(
    command: str,
    program_source: str,
    inputs: dict[str, Any],
    target: dict[str, Any],
    neighbours: list[dict[str, Any]],
) -> ExecutionOutput:
    prompt = (
        program_source
        + "\n\nINPUTS:\n"
        + json.dumps(inputs, ensure_ascii=False, indent=2)
        + "\n\nGRAPH CONTEXT:\n"
        + json.dumps({"target": target, "neighbours": neighbours}, ensure_ascii=False, indent=2)
        + "\n\nReturn JSON only."
    )
    completed = subprocess.run(
        shlex.split(command),
        input=prompt,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"local model command failed: {completed.stderr[-1000:]}")
    text = completed.stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("local model did not return a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("local model output must be a JSON object")
    return ExecutionOutput(value=value, executor_type="ollama_cli_prompt_program_v0")


def execute_registered_python_entrypoint(
    *,
    entrypoint: str | None,
    store: Any,
    inputs: dict[str, Any],
) -> ExecutionOutput:
    registry = {
        "mind_node_runtime.materialize:execute_materializer": _execute_materializer,
    }
    if not entrypoint or entrypoint not in registry:
        raise RuntimeError(f"unregistered python entrypoint: {entrypoint!r}")
    value = registry[entrypoint](store, inputs)
    if not isinstance(value, dict):
        raise ValueError("registered python entrypoint must return an object")
    return ExecutionOutput(value=value, executor_type="registered_python_entrypoint_v0")


def _execute_materializer(store: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    from .materialize import execute_materializer

    return execute_materializer(store, inputs)
