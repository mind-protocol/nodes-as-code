from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from mind_node_runtime.always_up import (
    ERROR_LOG_NODE_ID,
    ERROR_STREAM_NARRATIVE_ID,
    HEALTH_NODE_ID,
    LOG_STREAM_NARRATIVE_ID,
    SERVER_SPACE_ID,
    STREAM_DECORATOR_SPACE_ID,
    always_up_server_loop,
    record_server_error,
    record_stream_log,
)


class MockGraphStore:
    def __init__(self) -> None:
        self.written_queries = []
        self.error_stream_data = {"errors_json": "[]", "error_count": 0}
        self.error_log_data = {"errors_json": "[]", "error_count": 0}
        self.log_node_data = {"logs_json": "[]", "log_count": 0}

    def write(self, query: str, params: dict = None) -> list:
        params = params or {}
        self.written_queries.append((query, params))
        if params.get("id") == ERROR_STREAM_NARRATIVE_ID:
            if "errors_json" in params:
                self.error_stream_data["errors_json"] = params["errors_json"]
            if "count" in params:
                self.error_stream_data["error_count"] = params["count"]
        elif params.get("id") == ERROR_LOG_NODE_ID or ERROR_LOG_NODE_ID in query:
            if "errors_json" in params:
                self.error_log_data["errors_json"] = params["errors_json"]
            if "count" in params:
                self.error_log_data["error_count"] = params["count"]
        elif params.get("id") == LOG_STREAM_NARRATIVE_ID:
            if "logs_json" in params:
                self.log_node_data["logs_json"] = params["logs_json"]
            if "count" in params:
                self.log_node_data["log_count"] = params["count"]
        return []

    def read(self, query: str, params: dict = None) -> list:
        params = params or {}
        if params.get("id") == ERROR_STREAM_NARRATIVE_ID:
            return [[self.error_stream_data["errors_json"], self.error_stream_data["error_count"]]]
        if params.get("id") == ERROR_LOG_NODE_ID or ERROR_LOG_NODE_ID in query:
            return [[self.error_log_data["errors_json"], self.error_log_data["error_count"]]]
        if params.get("id") == LOG_STREAM_NARRATIVE_ID:
            return [[self.log_node_data["logs_json"], self.log_node_data["log_count"]]]
        if SERVER_SPACE_ID in query or STREAM_DECORATOR_SPACE_ID in query or params.get("space_id") in (SERVER_SPACE_ID, STREAM_DECORATOR_SPACE_ID):
            return [["Loop · Stream Logger Decorator v0", "active"]]
        return []


def test_record_stream_log():
    mock_store = MockGraphStore()
    log_entry = record_stream_log(mock_store, "Server started successfully", level="info", context="test")

    assert log_entry["message"] == "Server started successfully"
    assert mock_store.log_node_data["log_count"] == 1
    logs_list = json.loads(mock_store.log_node_data["logs_json"])
    assert len(logs_list) == 1
    assert logs_list[0]["message"] == "Server started successfully"


def test_record_server_error():
    mock_store = MockGraphStore()
    error_exc = RuntimeError("Simulated server crash test")
    
    result = record_server_error(mock_store, SERVER_SPACE_ID, error_exc, context="test_crash")

    assert result["context"] == "test_crash"
    assert "Simulated server crash test" in result["error"]

    # Verify health status update to 0
    queries_text = " ".join(q for q, _ in mock_store.written_queries)
    assert "SET s.health_status = 0" in queries_text
    assert "SET h.health_status = 0" in queries_text

    # Verify persistence to error stream narrative
    assert mock_store.error_stream_data["error_count"] == 1
    errors_list = json.loads(mock_store.error_stream_data["errors_json"])
    assert len(errors_list) == 1
    assert "Simulated server crash test" in errors_list[0]["error"]

    # Verify task creation in graph
    assert "created_task_id" in result
    assert "task:l2:mcp:server-incident-" in result["created_task_id"]
    assert "MERGE (t:RuntimeNode {id:$task_id})" in queries_text


def test_always_up_server_loop_restart():
    mock_store = MockGraphStore()
    call_count = 0

    @always_up_server_loop(max_restarts=3, backoff_seconds=0.01, graph_store=mock_store)
    def failing_server_fn():
        nonlocal call_count
        call_count += 1
        raise ValueError(f"Server failure attempt #{call_count}")

    with pytest.raises(ValueError) as exc_info:
        failing_server_fn()

    assert "attempt #3" in str(exc_info.value)
    assert call_count == 3
    assert mock_store.error_stream_data["error_count"] == 3
    errors_list = json.loads(mock_store.error_stream_data["errors_json"])
    assert len(errors_list) == 3
