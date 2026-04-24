"""Tests for agent.tool_guardrails — pure guardrail primitives for tool calls."""

import json
import pytest
from agent.tool_guardrails import (
    canonicalize_tool_args,
    compute_args_hash,
    detect_tool_failure,
    RepeatedFailureTracker,
    memory_argument_policy,
)


class TestCanonicalizeToolArgs:
    """Canonicalize tool call args with sorted compact JSON."""

    def test_empty_dict(self):
        assert canonicalize_tool_args({}) == "{}"

    def test_sorted_keys(self):
        args = {"z": 1, "a": 2, "b": 3}
        canonical = canonicalize_tool_args(args)
        # Expect keys sorted alphabetically, compact (no spaces)
        assert canonical == '{"a":2,"b":3,"z":1}'

    def test_nested_structure(self):
        args = {"b": {"y": 2, "x": 1}, "a": [3, 2, 1]}
        canonical = canonicalize_tool_args(args)
        # Nested dicts and lists should also be canonicalized (sorted keys inside)
        assert canonical == '{"a":[3,2,1],"b":{"x":1,"y":2}}'

    def test_non_dict_input_raises(self):
        with pytest.raises(TypeError):
            canonicalize_tool_args("not a dict")
        with pytest.raises(TypeError):
            canonicalize_tool_args(None)


class TestComputeArgsHash:
    """Hash of canonical args string."""

    def test_hash_of_empty(self):
        h = compute_args_hash("{}")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA256 hex

    def test_hash_consistency(self):
        canonical = '{"a":1}'
        h1 = compute_args_hash(canonical)
        h2 = compute_args_hash(canonical)
        assert h1 == h2

    def test_hash_of_different_strings(self):
        h1 = compute_args_hash('{"a":1}')
        h2 = compute_args_hash('{"a":2}')
        assert h1 != h2


class TestDetectToolFailure:
    """Detect failure for various tool result patterns."""

    # JSON success: false
    def test_json_success_false(self):
        result = json.dumps({"success": False})
        assert detect_tool_failure("any_tool", result) is True

    def test_json_success_false_with_error(self):
        result = json.dumps({"success": False, "error": "something went wrong"})
        assert detect_tool_failure("any_tool", result) is True

    # JSON non-empty error
    def test_json_error_nonempty(self):
        result = json.dumps({"error": "something"})
        assert detect_tool_failure("any_tool", result) is True

    def test_json_error_empty(self):
        result = json.dumps({"error": ""})
        assert detect_tool_failure("any_tool", result) is False

    # Terminal nonzero exit code
    def test_terminal_exit_code_nonzero(self):
        result = json.dumps({"exit_code": 1})
        assert detect_tool_failure("terminal", result) is True

    def test_terminal_exit_code_zero(self):
        result = json.dumps({"exit_code": 0})
        assert detect_tool_failure("terminal", result) is False

    # Python exception-shaped strings (e.g., "Traceback ...")
    def test_exception_traceback(self):
        result = "Traceback (most recent call last):\n  File ..."
        assert detect_tool_failure("any_tool", result) is True

    # Obvious error strings (e.g., "Error:", "failed")
    def test_error_prefix(self):
        result = "Error: something"
        assert detect_tool_failure("any_tool", result) is True

    def test_failed_substring(self):
        # "failed" substring without quotes is not considered an error
        result = "The operation failed successfully"
        assert detect_tool_failure("any_tool", result) is False

    def test_failed_json_key(self):
        # JSON key "failed" should be detected as failure
        result = '{"failed": true}'
        assert detect_tool_failure("any_tool", result) is True

    # Successful empty content / empty reads should NOT be failures
    def test_empty_string_success(self):
        assert detect_tool_failure("any_tool", "") is False

    def test_empty_json_success(self):
        result = json.dumps({"success": True})
        assert detect_tool_failure("any_tool", result) is False

    def test_empty_read_file_result(self):
        # read_file returns empty string for empty file
        result = ""
        assert detect_tool_failure("read_file", result) is False

    # Memory-specific: "full" detection
    def test_memory_full(self):
        result = json.dumps({"success": False, "error": "exceed the limit"})
        assert detect_tool_failure("memory", result) is True

    # Generic heuristic: should not flag successful results
    def test_generic_success(self):
        result = json.dumps({"data": "ok"})
        assert detect_tool_failure("any_tool", result) is False


class TestRepeatedFailureTracker:
    """Track consecutive identical failed tool calls by (tool_name, canonical_args_hash)."""

    def test_initial_state(self):
        tracker = RepeatedFailureTracker()
        assert tracker.failure_count("foo", "hash123") == 0

    def test_increment_on_failure(self):
        tracker = RepeatedFailureTracker()
        tracker.record_failure("foo", "hash123")
        assert tracker.failure_count("foo", "hash123") == 1

    def test_multiple_failures_same_key(self):
        tracker = RepeatedFailureTracker()
        tracker.record_failure("foo", "hash123")
        tracker.record_failure("foo", "hash123")
        assert tracker.failure_count("foo", "hash123") == 2

    def test_different_tool_name_resets_previous_streak(self):
        tracker = RepeatedFailureTracker()
        tracker.record_failure("foo", "hash123")
        # Different tool name resets previous streak
        tracker.record_failure("bar", "hash123")
        # Previous streak for foo is reset (should be 0 because not current key)
        assert tracker.failure_count("foo", "hash123") == 0
        # New streak for bar starts at 1
        assert tracker.failure_count("bar", "hash123") == 1

    def test_different_args_hash_resets_previous_streak(self):
        tracker = RepeatedFailureTracker()
        tracker.record_failure("foo", "hash123")
        tracker.record_failure("foo", "hash123")
        # Different args hash resets previous streak
        tracker.record_failure("foo", "hash456")
        # Previous streak for hash123 is reset (should be 0 because not current key)
        assert tracker.failure_count("foo", "hash123") == 0
        # New streak for hash456 starts at 1
        assert tracker.failure_count("foo", "hash456") == 1

    def test_success_resets_current_streak(self):
        tracker = RepeatedFailureTracker()
        tracker.record_failure("foo", "hash123")
        tracker.record_failure("foo", "hash123")
        tracker.reset_on_success("foo", "hash123")
        # Streak for current key is reset
        assert tracker.failure_count("foo", "hash123") == 0
        # Current key remains the same; subsequent failure increments from 0
        tracker.record_failure("foo", "hash123")
        assert tracker.failure_count("foo", "hash123") == 1

    def test_returning_to_old_hash_starts_at_one(self):
        tracker = RepeatedFailureTracker()
        # First streak for hash123
        tracker.record_failure("foo", "hash123")
        tracker.record_failure("foo", "hash123")
        # Different hash resets previous streak
        tracker.record_failure("foo", "hash456")
        # Return to hash123 (old hash) should start at 1, not cumulative
        tracker.record_failure("foo", "hash123")
        assert tracker.failure_count("foo", "hash123") == 1
        # hash456 is no longer current after returning to hash123.
        assert tracker.failure_count("foo", "hash456") == 0  # not current key

    def test_block_decision(self):
        tracker = RepeatedFailureTracker(threshold=3)
        tracker.record_failure("foo", "hash123")
        tracker.record_failure("foo", "hash123")
        tracker.record_failure("foo", "hash123")
        assert tracker.should_block("foo", "hash123") is True
        # Different key should not be blocked
        assert tracker.should_block("foo", "hash456") is False
        # Different tool should not be blocked
        assert tracker.should_block("bar", "hash123") is False

class TestMemoryArgumentPolicy:
    """Reject display artifacts in old_text / content."""

    def test_reject_truncated(self):
        assert memory_argument_policy({"content": "[truncated]"}) is False
        assert memory_argument_policy({"old_text": "[truncated]"}) is False

    def test_reject_ellipsis(self):
        assert memory_argument_policy({"content": "[...]"}) is False
        assert memory_argument_policy({"old_text": "[...]"}) is False

    def test_reject_cont(self):
        assert memory_argument_policy({"content": "[cont]"}) is False
        assert memory_argument_policy({"old_text": "[cont]"}) is False

    def test_reject_more(self):
        assert memory_argument_policy({"content": "[more]"}) is False
        assert memory_argument_policy({"old_text": "[more]"}) is False

    def test_accept_normal_string(self):
        assert memory_argument_policy({"content": "some content"}) is True
        assert memory_argument_policy({"old_text": "some old text"}) is True

    def test_non_string_args_cleanly(self):
        # Non-string content should be rejected without raising TypeError.
        assert memory_argument_policy({"content": 123}) is False
        assert memory_argument_policy({"old_text": ["list"]}) is False
        assert memory_argument_policy({"content": None}) is False
        assert memory_argument_policy({"content": ""}) is True

    def test_missing_key(self):
        assert memory_argument_policy({}) is True
        assert memory_argument_policy({"action": "add"}) is True