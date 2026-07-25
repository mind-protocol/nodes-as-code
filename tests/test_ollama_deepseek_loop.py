"""
Loop validation · Always-Up ollama run deepseek-r1:14b.

Covers:
  1. Validation      : worker RAISES on subprocess exit (so @always_up restarts).
  2. Restart wiring   : @always_up supervises and restarts the worker on crash.
  3. Observer validation:
       - offline Ollama  -> measurement_failed (NOT healthy)
       - model missing   -> known_absent       (NOT healthy)
       - model present   -> observed / healthy
     i.e. missing evidence is never converted into success.
  4. Graph seed builds the causal chain and links the decorator loop.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mind_node_runtime import ollama_deepseek_loop as loop
from mind_node_runtime.ollama_deepseek_loop import (
    CODE_NODE_ID,
    LOOP_SPACE_ID,
    OBSERVER_NODE_ID,
    OllamaProcessExited,
    observe_deepseek_health,
)


# --------------------------------------------------------------------------- #
# 1 + 2. Worker raises on subprocess exit; @always_up restarts it.            #
# --------------------------------------------------------------------------- #
def test_worker_raises_on_subprocess_exit():
    """The undecorated worker body must RAISE when the process is already dead."""
    fake_proc = MagicMock()
    fake_proc.poll.return_value = 0  # process already exited -> heartbeat returns immediately

    with patch.object(loop.subprocess, "Popen", return_value=fake_proc) as popen, \
         patch.object(loop, "_graph_store", return_value=None), \
         patch.object(loop, "_ensure_model_pulled", return_value=None):
        raw = loop.run_deepseek_r1_14b.__wrapped__
        with pytest.raises(OllamaProcessExited) as exc_info:
            raw("ollama run deepseek-r1:14b")

    popen.assert_called_once()
    # stdin held open so the resident REPL does not exit on EOF
    assert popen.call_args.kwargs.get("stdin") == loop.subprocess.PIPE
    assert "return code 0" in str(exc_info.value)


def test_missing_ollama_binary_raises_for_restart():
    with patch.object(loop.subprocess, "Popen", side_effect=FileNotFoundError("ollama")), \
         patch.object(loop, "_graph_store", return_value=None), \
         patch.object(loop, "_ensure_model_pulled", return_value=None):
        raw = loop.run_deepseek_r1_14b.__wrapped__
        with pytest.raises(OllamaProcessExited):
            raw("ollama run deepseek-r1:14b")


def test_ensure_model_pulled_pulls_when_absent():
    absent = {"information_status": "known_absent", "healthy": False, "reason": "missing"}
    fake_completed = MagicMock()
    fake_completed.returncode = 0
    with patch.object(loop, "observe_deepseek_health", return_value=absent), \
         patch.object(loop.subprocess, "run", return_value=fake_completed) as run:
        loop._ensure_model_pulled(store=None, model="deepseek-r1:14b")
    run.assert_called_once_with(["ollama", "pull", "deepseek-r1:14b"])


def test_ensure_model_pulled_skips_when_present():
    present = {"information_status": "observed", "healthy": True}
    with patch.object(loop, "observe_deepseek_health", return_value=present), \
         patch.object(loop.subprocess, "run") as run:
        loop._ensure_model_pulled(store=None, model="deepseek-r1:14b")
    run.assert_not_called()


def test_ensure_model_pulled_raises_on_pull_failure():
    absent = {"information_status": "known_absent", "healthy": False, "reason": "missing"}
    fake_completed = MagicMock()
    fake_completed.returncode = 1
    with patch.object(loop, "observe_deepseek_health", return_value=absent), \
         patch.object(loop.subprocess, "run", return_value=fake_completed):
        with pytest.raises(OllamaProcessExited):
            loop._ensure_model_pulled(store=None, model="deepseek-r1:14b")


def test_always_up_restarts_worker_on_crash():
    """@always_up supervises: the worker is retried up to max_restarts on crash."""
    mock_store = MagicMock()
    mock_store.read.return_value = []
    call_count = 0

    @loop.always_up(space_id=LOOP_SPACE_ID, max_restarts=3, backoff_seconds=0.0, graph_store=mock_store)
    def crashing_worker():
        nonlocal call_count
        call_count += 1
        raise OllamaProcessExited(f"exit #{call_count}")

    with pytest.raises(OllamaProcessExited):
        crashing_worker()

    assert call_count == 3  # restarted until max_restarts reached


# --------------------------------------------------------------------------- #
# 3. Observer validation — never convert missing evidence into success.       #
# --------------------------------------------------------------------------- #
def test_observer_reports_measurement_failed_when_offline():
    with patch.object(loop.urllib.request, "urlopen", side_effect=OSError("connection refused")):
        result = observe_deepseek_health(model="deepseek-r1:14b")
    assert result["information_status"] == "measurement_failed"
    assert result["healthy"] is False


def test_observer_reports_known_absent_when_model_missing():
    payload = json.dumps({"models": [{"name": "qwen2.5:1.5b"}]}).encode("utf-8")
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.read.return_value = payload
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False

    with patch.object(loop.urllib.request, "urlopen", return_value=fake_resp):
        result = observe_deepseek_health(model="deepseek-r1:14b")

    assert result["information_status"] == "known_absent"
    assert result["healthy"] is False


def test_observer_reports_observed_when_model_present():
    payload = json.dumps(
        {"models": [{"name": "deepseek-r1:14b"}, {"name": "qwen2.5:1.5b"}]}
    ).encode("utf-8")
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.read.return_value = payload
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False

    with patch.object(loop.urllib.request, "urlopen", return_value=fake_resp):
        result = observe_deepseek_health(model="deepseek-r1:14b")

    assert result["information_status"] == "observed"
    assert result["healthy"] is True
    assert "deepseek-r1:14b" in result["available_tags"]


# --------------------------------------------------------------------------- #
# 4. Graph seed builds the causal chain and links the decorator loop.         #
# --------------------------------------------------------------------------- #
def test_seed_builds_causal_chain_and_links_decorator_loop():
    from mind_node_runtime.ollama_deepseek_loop_seed import (
        STREAM_DECORATOR_SPACE_ID,
        seed_ollama_deepseek_loop,
    )

    store = MagicMock()
    result = seed_ollama_deepseek_loop(store)

    assert result["status"] == "success"
    assert result["loop_space"] == LOOP_SPACE_ID
    assert result["governed_by"] == STREAM_DECORATOR_SPACE_ID

    queries = " ".join(str(c.args[0]) for c in store.write.call_args_list)
    # Causal chain relations present
    for rel in [
        "DEFINED_BY_CODE",
        "OBSERVED_BY",
        "HAS_HEALTH",
        "SERVES_OBJECTIVE",
        "VERIFIES",
        "WRAPPED_BY_DECORATOR",
        "GOVERNED_BY_DECORATOR_LOOP",
    ]:
        assert rel in queries, f"missing relation {rel} in seed"

    # IDs are passed as bound parameters, not inlined into Cypher.
    all_params = {}
    for c in store.write.call_args_list:
        if len(c.args) > 1 and isinstance(c.args[1], dict):
            all_params.update(c.args[1])
    assert all_params.get("code_id") == CODE_NODE_ID
    assert all_params.get("obs_id") == OBSERVER_NODE_ID
    assert all_params.get("space_id") == LOOP_SPACE_ID
