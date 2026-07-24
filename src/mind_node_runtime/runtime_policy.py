from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimePolicy:
    loop_sleep_seconds: float = 0.25
    heartbeat_interval_seconds: float = 15.0
    watchdog_timeout_seconds: float = 60.0
    config_refresh_seconds: float = 2.0

    @classmethod
    def from_row(cls, row: list[Any] | None) -> "RuntimePolicy":
        if not row:
            return cls()
        return cls(
            loop_sleep_seconds=max(0.05, float(row[0] or 0.25)),
            heartbeat_interval_seconds=max(1.0, float(row[1] or 15.0)),
            watchdog_timeout_seconds=max(5.0, float(row[2] or 60.0)),
            config_refresh_seconds=max(0.25, float(row[3] or 2.0)),
        )
