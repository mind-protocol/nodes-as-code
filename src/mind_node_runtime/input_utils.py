from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_json_input(raw: str | None, file_path: str | None) -> dict[str, Any]:
    if raw and file_path:
        raise ValueError("use either --inputs or --inputs-file, not both")
    if file_path:
        value = json.loads(Path(file_path).read_text(encoding="utf-8"))
    else:
        value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("inputs must be a JSON object")
    return value
