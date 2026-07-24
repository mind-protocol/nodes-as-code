from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .config import Settings
if TYPE_CHECKING:
    from .graph import GraphStore
from .hashing import canonical_json, sha256_text

MANIFEST_NAME = ".mind-code-manifest.json"
DEFAULT_OUTPUT_DIR = ".mind/generated/code"
GRAPH_AUTHORITY_MODES = {"graph_source", "graph_structured_definition"}


class CodeNodeStore(Protocol):
    def list_code_nodes(self) -> list[dict[str, Any]]:
        ...

    def load_code_node(self, program_id: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class MaterializedCode:
    program_id: str
    path: str
    content_hash: str
    version: str | None
    language: str | None
    artifact_kind: str | None
    authority_mode: str | None
    source_kind: str
    declared_hash: str | None
    declared_hash_matches: bool | None
    synced_at: str


@dataclass(frozen=True)
class SyncOutcome:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    metadata_only: int = 0
    errors: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    segment = segment.strip(".-")
    return segment or "unnamed"


def extension_for(node: dict[str, Any], source_kind: str) -> str:
    if source_kind != "source":
        return ".json"

    language = str(node.get("language") or "").lower().replace("-", "_")
    artifact = str(node.get("artifact_kind") or "").lower()
    mapping = {
        "python": ".py",
        "py": ".py",
        "typescript": ".ts",
        "ts": ".ts",
        "javascript": ".js",
        "js": ".js",
        "prompt_markdown": ".md",
        "markdown": ".md",
        "md": ".md",
        "yaml": ".yaml",
        "yml": ".yaml",
        "json": ".json",
        "cypher": ".cypher",
        "sql": ".sql",
        "shell": ".sh",
        "bash": ".sh",
        "powershell": ".ps1",
    }
    if language in mapping:
        return mapping[language]
    if artifact == "prompt_program":
        return ".md"
    return ".txt"


def relative_path_for(node: dict[str, Any], source_kind: str) -> Path:
    program_id = str(node["id"])
    parts = [safe_segment(part) for part in program_id.split(":")]
    extension = extension_for(node, source_kind)
    if len(parts) == 1:
        return Path(parts[0] + extension)
    return Path(*parts[:-1], parts[-1] + extension)


def _parse_json_if_possible(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def canonical_payload(node: dict[str, Any]) -> tuple[str, str]:
    source = node.get("source")
    if isinstance(source, str) and source != "":
        return source, "source"

    structured = node.get("structured_definition")
    if structured is None:
        structured = _parse_json_if_possible(node.get("structured_definition_json"))

    content = _parse_json_if_possible(node.get("content"))
    payload = {
        "id": node.get("id"),
        "node_type": node.get("node_type"),
        "subtype": node.get("subtype"),
        "name": node.get("name"),
        "version": node.get("version"),
        "language": node.get("language"),
        "artifactKind": node.get("artifact_kind"),
        "authorityMode": node.get("authority_mode"),
        "executorType": node.get("executor_type"),
        "status": node.get("status"),
        "structuredDefinition": structured,
        "content": content,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", "structured_node"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(content, encoding="utf-8", newline="")
    os.replace(temporary, path)


def read_manifest(output_root: Path) -> dict[str, Any]:
    path = output_root / MANIFEST_NAME
    if not path.exists():
        return {"schemaVersion": 1, "programs": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": 1, "programs": {}}
    if not isinstance(value, dict) or not isinstance(value.get("programs"), dict):
        return {"schemaVersion": 1, "programs": {}}
    return value


def write_manifest(output_root: Path, manifest: dict[str, Any]) -> None:
    manifest["schemaVersion"] = 1
    manifest["generatedAt"] = utc_now()
    atomic_write(
        output_root / MANIFEST_NAME,
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def materialize_node(
    node: dict[str, Any],
    *,
    output_root: Path,
    manifest: dict[str, Any],
) -> tuple[MaterializedCode, str]:
    content, source_kind = canonical_payload(node)
    content_hash = sha256_text(content)
    relative_path = relative_path_for(node, source_kind)
    destination = output_root / relative_path

    previous = manifest["programs"].get(node["id"])
    previous_hash = previous.get("contentHash") if isinstance(previous, dict) else None
    existed = destination.exists()
    local_hash = None
    if existed:
        try:
            local_hash = sha256_text(destination.read_text(encoding="utf-8"))
        except OSError:
            local_hash = None

    if existed and local_hash == content_hash and previous_hash == content_hash:
        change = "unchanged"
    else:
        atomic_write(destination, content)
        change = "updated" if existed else "created"

    declared_hash = node.get("source_hash")
    declared_match: bool | None = None
    if declared_hash:
        declared_match = str(declared_hash) == content_hash

    record = MaterializedCode(
        program_id=str(node["id"]),
        path=relative_path.as_posix(),
        content_hash=content_hash,
        version=node.get("version"),
        language=node.get("language"),
        artifact_kind=node.get("artifact_kind"),
        authority_mode=node.get("authority_mode"),
        source_kind=source_kind,
        declared_hash=str(declared_hash) if declared_hash else None,
        declared_hash_matches=declared_match,
        synced_at=utc_now(),
    )
    manifest["programs"][node["id"]] = {
        "path": record.path,
        "contentHash": record.content_hash,
        "version": record.version,
        "language": record.language,
        "artifactKind": record.artifact_kind,
        "authorityMode": record.authority_mode,
        "sourceKind": record.source_kind,
        "declaredHash": record.declared_hash,
        "declaredHashMatches": record.declared_hash_matches,
        "syncedAt": record.synced_at,
    }
    return record, change


def sync_all(
    store: CodeNodeStore,
    output_root: Path,
    *,
    include_non_graph_authority: bool = True,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(output_root)
    manifest.setdefault("programs", {})
    outcome = SyncOutcome()
    records: list[dict[str, Any]] = []

    for node in store.list_code_nodes():
        authority_mode = node.get("authority_mode")
        if not include_non_graph_authority and authority_mode not in GRAPH_AUTHORITY_MODES:
            continue
        try:
            record, change = materialize_node(node, output_root=output_root, manifest=manifest)
            values = asdict(outcome)
            values[change] += 1
            if record.source_kind != "source":
                values["metadata_only"] += 1
            outcome = SyncOutcome(**values)
            records.append(asdict(record))
        except Exception as exc:  # one malformed node must not block the entire cache refresh
            values = asdict(outcome)
            values["errors"] += 1
            outcome = SyncOutcome(**values)
            records.append({"program_id": node.get("id"), "error": str(exc)})

    write_manifest(output_root, manifest)
    return {
        "status": "completed" if outcome.errors == 0 else "completed_with_errors",
        "outputRoot": str(output_root.resolve()),
        **asdict(outcome),
        "programs": records,
    }


def resolve_program(
    store: CodeNodeStore,
    program_id: str,
    output_root: Path,
    *,
    materialize: bool = True,
) -> dict[str, Any]:
    node = store.load_code_node(program_id)
    content, source_kind = canonical_payload(node)
    content_hash = sha256_text(content)
    relative_path = relative_path_for(node, source_kind)
    destination = output_root / relative_path

    manifest = read_manifest(output_root)
    entry = manifest.get("programs", {}).get(program_id, {})
    local_fresh = False
    if destination.exists() and entry.get("contentHash") == content_hash:
        try:
            local_fresh = sha256_text(destination.read_text(encoding="utf-8")) == content_hash
        except OSError:
            local_fresh = False

    resolution = "local_fresh"
    if not local_fresh:
        resolution = "graph_live"
        if materialize:
            manifest.setdefault("programs", {})
            materialize_node(node, output_root=output_root, manifest=manifest)
            write_manifest(output_root, manifest)

    return {
        "programId": program_id,
        "resolution": resolution,
        "path": str(destination.resolve()) if materialize or local_fresh else None,
        "content": content,
        "contentHash": content_hash,
        "sourceKind": source_kind,
        "version": node.get("version"),
        "authorityMode": node.get("authority_mode"),
    }



def execute_materializer(store: CodeNodeStore, inputs: dict[str, Any]) -> dict[str, Any]:
    """Registered Node-as-Code entrypoint used by the graph-authorized worker."""
    operation = str(inputs.get("operation") or "sync")
    repo_root = Path(str(inputs.get("repoRoot") or ".")).expanduser().resolve()
    output_dir = Path(str(inputs.get("outputDir") or DEFAULT_OUTPUT_DIR))
    output_root = output_dir.resolve() if output_dir.is_absolute() else repo_root / output_dir
    if operation == "sync":
        return sync_all(
            store,
            output_root,
            include_non_graph_authority=not bool(inputs.get("graphAuthorityOnly", False)),
        )
    if operation == "resolve":
        program_id = inputs.get("programIdToResolve")
        if not isinstance(program_id, str) or not program_id:
            raise ValueError("programIdToResolve is required for resolve")
        result = resolve_program(
            store,
            program_id,
            output_root,
            materialize=bool(inputs.get("materialize", True)),
        )
        result.pop("content", None)
        return result
    raise ValueError(f"unsupported materializer operation: {operation}")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize graph-authoritative code nodes into a repository cache."
    )
    parser.add_argument("--graph", help="FalkorDB graph name; defaults to FALKOR_GRAPH")
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository root receiving the derived cache (default: current directory)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Derived cache directory inside the repository (default: {DEFAULT_OUTPUT_DIR})",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="Materialize every code node once")
    sync.add_argument(
        "--graph-authority-only",
        action="store_true",
        help="Exclude file_legacy/external capability metadata nodes",
    )

    watch = sub.add_parser("watch", help="Synchronize periodically until interrupted")
    watch.add_argument("--interval", type=float, default=30.0)
    watch.add_argument("--graph-authority-only", action="store_true")

    resolve = sub.add_parser(
        "resolve", help="Use a fresh local copy or fetch the program live from the graph"
    )
    resolve.add_argument("--program", required=True)
    resolve.add_argument("--stdout", action="store_true", dest="print_content")
    resolve.add_argument(
        "--no-materialize",
        action="store_true",
        help="Fetch live without writing the derived cache",
    )
    return parser


def make_store(args: argparse.Namespace) -> "GraphStore":
    from .graph import GraphStore

    settings = Settings()
    if args.graph:
        settings = Settings(
            host=settings.host,
            port=settings.port,
            graph_name=args.graph,
            username=settings.username,
            password=settings.password,
            worker_id=settings.worker_id,
            poll_seconds=settings.poll_seconds,
            lease_seconds=settings.lease_seconds,
            executor_mode=settings.executor_mode,
            model_command=settings.model_command,
        )
    return GraphStore(settings)


def output_root_from(args: argparse.Namespace) -> Path:
    repo = Path(args.repo).expanduser().resolve()
    output = Path(args.output_dir)
    return output.resolve() if output.is_absolute() else repo / output


def main() -> None:
    args = build_parser().parse_args()
    store = make_store(args)
    output_root = output_root_from(args)

    if args.command == "sync":
        result = sync_all(
            store,
            output_root,
            include_non_graph_authority=not args.graph_authority_only,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(1 if result["errors"] else 0)

    if args.command == "resolve":
        result = resolve_program(
            store,
            args.program,
            output_root,
            materialize=not args.no_materialize,
        )
        if args.print_content:
            sys.stdout.write(result.pop("content"))
            if not result["contentHash"]:
                sys.stdout.write("\n")
        else:
            result.pop("content", None)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")

    try:
        while True:
            result = sync_all(
                store,
                output_root,
                include_non_graph_authority=not args.graph_authority_only,
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped_by_user"}))


if __name__ == "__main__":
    main()
