from pathlib import Path
import pytest

from mind_node_runtime import always_up, scan_undecorated_loops


class MockGraphStore:
    def __init__(self) -> None:
        self.written_queries = []

    def write(self, query: str, params: dict = None) -> list:
        self.written_queries.append((query, params or {}))
        return []

    def read(self, query: str, params: dict = None) -> list:
        return [["Loop · Test v0", "active"]]


def test_zero_config_always_up_decorator():
    mock_store = MockGraphStore()
    executed = False

    @always_up(graph_store=mock_store)
    def my_worker_func():
        nonlocal executed
        executed = True
        return 42

    result = my_worker_func()
    assert result == 42
    assert executed is True

    # Check auto-linking query execution
    queries_text = " ".join(q for q, _ in mock_store.written_queries)
    assert "MERGE (s:RuntimeNode {id:$space_id})" in queries_text
    assert "MERGE (c)-[:USES_DECORATOR]->(cd)" in queries_text
    assert "MERGE (s)-[:WRAPPED_BY_DECORATOR]->(ld)" in queries_text


def test_scan_undecorated_loops(tmp_path: Path):
    sample_code = """
def main():
    while True:
        print("Running undecorated main loop")

@always_up
def decorated_worker():
    while True:
        print("Running decorated worker loop")
"""
    test_file = tmp_path / "sample_script.py"
    test_file.write_text(sample_code, encoding="utf-8")

    results = scan_undecorated_loops(tmp_path)
    assert len(results) == 1
    assert results[0]["function"] == "main"
    assert "Add @always_up to function 'main'" in results[0]["recommendation"]
