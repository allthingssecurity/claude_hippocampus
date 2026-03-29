"""Integration tests for CA3 associative memory layer.

These tests run against the live Neo4j instance at localhost:7475.
They require COACTIVATED edges to have been bootstrapped first.
"""

import sys
import os
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ca3.neo4j_client import Neo4jClient
from ca3.activation import activate, extract_keywords, ActivationResult
from ca3.context_packet import compress_to_packet
from ca3.scorer import rank_activation


def test_neo4j_connectivity():
    """Neo4j should be reachable."""
    db = Neo4jClient()
    rows = db.query("RETURN 1 AS ok")
    assert rows == [{"ok": 1}]
    db.close()


def test_coactivated_edges_exist():
    """Bootstrap should have created COACTIVATED edges."""
    db = Neo4jClient()
    rows = db.query("MATCH ()-[c:COACTIVATED]-() RETURN count(c) AS total")
    assert rows[0]["total"] > 0, "No COACTIVATED edges found — run build-coactivations.sh first"
    db.close()


def test_extract_keywords():
    """Keywords should be extracted, stopwords removed."""
    kw = extract_keywords("help me fix the bash agent training script")
    assert "bash" in kw
    assert "agent" in kw
    assert "training" in kw
    assert "script" in kw
    # Stopwords removed
    assert "help" not in kw
    assert "the" not in kw
    assert "me" not in kw
    # Bigrams should be present
    assert any(" " in k for k in kw), f"Expected bigrams in {kw}"


def test_extract_keywords_empty():
    kw = extract_keywords("the a an is")
    assert kw == []


def test_activate_returns_result():
    """Activation should return an ActivationResult with nodes."""
    result = activate("bash agent")
    assert isinstance(result, ActivationResult)
    assert result.elapsed_ms > 0
    assert len(result.debug_trace) > 0


def test_activate_finds_seeds():
    """Activation should find seed entities for known keywords."""
    result = activate("bash agent training")
    assert len(result.nodes) > 0
    names = [n.name.lower() for n in result.nodes]
    assert any("agent" in n for n in names), f"Expected 'agent' in seeds, got: {names}"


def test_activate_spreads():
    """Activation should traverse COACTIVATED edges to find neighbors."""
    result = activate("bash agent training pipeline")
    spread_nodes = [n for n in result.nodes if n.source.startswith("spread")]
    # With well-connected entities, we should get spread nodes
    if result.edges_traversed > 0:
        assert len(spread_nodes) > 0, "Edges traversed but no spread nodes collected"


def test_activate_timeout():
    """Activation should complete within timeout even with broad cues."""
    result = activate("code project file system error bug fix", timeout_ms=2000)
    assert result.elapsed_ms < 3000  # Some margin


def test_context_packet_format():
    """Context packet should be properly formatted."""
    result = activate("bash agent training")
    if result.nodes:
        packet = compress_to_packet(result)
        assert "[Associative recall" in packet
        assert "concepts" in packet
        assert len(packet) < 6000  # Under token limit


def test_context_packet_empty():
    """Empty result should produce empty packet."""
    result = ActivationResult()
    packet = compress_to_packet(result)
    assert packet == ""


def test_scorer_workspace_boost():
    """Workspace matching should boost activation."""
    base = rank_activation(1.0, "contextgraph", "/Users/foo/contextgraph")
    no_match = rank_activation(1.0, "something_else", "/Users/foo/contextgraph")
    assert base > no_match


def test_hook_integration():
    """Hook script should return valid JSON for UserPromptSubmit."""
    hook_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "hooks", "ca3-activation-hook.py",
    )
    input_json = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "user_prompt": "help me fix the bash agent training script",
        "cwd": "/Users/I074560/Downloads/experiments/codexapp",
    })
    proc = subprocess.run(
        [sys.executable, hook_path],
        input=input_json,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    response = json.loads(proc.stdout)
    assert response["continue"] is True


def test_hook_skips_short_prompt():
    """Hook should skip very short prompts."""
    hook_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "hooks", "ca3-activation-hook.py",
    )
    input_json = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "user_prompt": "hi",
        "cwd": "/tmp",
    })
    proc = subprocess.run(
        [sys.executable, hook_path],
        input=input_json,
        capture_output=True,
        text=True,
        timeout=10,
    )
    response = json.loads(proc.stdout)
    assert response == {"continue": True}


def test_hook_skips_non_submit():
    """Hook should pass through non-UserPromptSubmit events."""
    hook_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "hooks", "ca3-activation-hook.py",
    )
    input_json = json.dumps({
        "hook_event_name": "SessionStart",
        "cwd": "/tmp",
    })
    proc = subprocess.run(
        [sys.executable, hook_path],
        input=input_json,
        capture_output=True,
        text=True,
        timeout=10,
    )
    response = json.loads(proc.stdout)
    assert response == {"continue": True}


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
