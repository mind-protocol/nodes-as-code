"""Always-on Git projection sync loop.

The graph is canonical; Git is the append-only recovery log for filesystem
materializations. Every stable workspace mutation is staged, committed and
pushed to main. Any command failure raises so @always_up emits a graph incident.
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .always_up import always_up, record_stream_log
from .config import Settings
from .graph import GraphStore

REPO_ROOT = Path(__file__).resolve().parents[2]
SPACE_ID = "space:l2:git-projection-sync-loop-v0"
POLL_SECONDS = float(os.getenv("MIND_GIT_SYNC_POLL_SECONDS", "5"))
STABILIZE_SECONDS = float(os.getenv("MIND_GIT_SYNC_STABILIZE_SECONDS", "12"))
BRANCH = os.getenv("MIND_GIT_SYNC_BRANCH", "main")
REMOTE = os.getenv("MIND_GIT_SYNC_REMOTE", "origin")


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=180
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({completed.returncode})\n"
            f"stdout: {completed.stdout[-8000:]}\nstderr: {completed.stderr[-8000:]}"
        )
    return completed


def _status() -> str:
    return _git("status", "--porcelain=v1").stdout


def _current_branch() -> str:
    return _git("branch", "--show-current").stdout.strip()


def _commit_message() -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"chore(sync): filesystem projection {now}"


def _sync_once(graph: GraphStore) -> bool:
    before = _status()
    if not before:
        return False

    time.sleep(STABILIZE_SECONDS)
    after = _status()
    if after != before:
        return False

    branch = _current_branch()
    if branch != BRANCH:
        raise RuntimeError(f"Git sync refuses branch {branch!r}; canonical branch is {BRANCH!r}")

    _git("add", "-A")
    staged = _git("diff", "--cached", "--name-status").stdout.strip()
    if not staged:
        return False

    _git("commit", "-m", _commit_message())
    commit = _git("rev-parse", "HEAD").stdout.strip()
    _git("pull", "--rebase", REMOTE, BRANCH)
    _git("push", REMOTE, f"HEAD:{BRANCH}")

    record_stream_log(
        graph,
        f"Git projection committed and pushed: {commit}\n{staged}",
        level="info",
        context="git_projection_sync_success",
    )
    return True


@always_up(space_id=SPACE_ID, backoff_seconds=15.0)
def run_git_projection_sync_loop() -> None:
    graph = GraphStore(Settings())
    while True:
        _sync_once(graph)
        time.sleep(POLL_SECONDS)


def main() -> None:
    run_git_projection_sync_loop()


if __name__ == "__main__":
    main()
