from __future__ import annotations

import os
from dataclasses import dataclass


def _optional(value: str | None) -> str | None:
    return value if value else None


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("FALKOR_HOST", "127.0.0.1")
    port: int = int(os.getenv("FALKOR_PORT", "6379"))
    graph_name: str = os.getenv("FALKOR_GRAPH", "mind_kernel_v0")
    username: str | None = _optional(os.getenv("FALKOR_USERNAME"))
    password: str | None = _optional(os.getenv("FALKOR_PASSWORD"))
    worker_id: str = os.getenv("MIND_WORKER_ID", "worker-local-1")
    poll_seconds: float = float(os.getenv("MIND_POLL_SECONDS", "0.5"))
    lease_seconds: int = int(os.getenv("MIND_LEASE_SECONDS", "120"))
    executor_mode: str = os.getenv("MIND_EXECUTOR_MODE", "deterministic")
    model_command: str | None = _optional(os.getenv("MIND_MODEL_COMMAND"))
