"""Tests for the agent loop guardrail system.

Run with: python -m pytest test_guardrails.py -v
"""

import json
import pytest
from agent.tool_loop_detector import ToolLoopDetector, ToolLoopError, create_detector
from agent.memory_tool_validator import MemoryToolValidator, MemoryValidationError, create_validator
from agent.task_state_preserver import TaskStatePreserver, create_preserver
from agent.agent_loop_guardrails import GuardrailManager


class TestToolLoopDetector:
    """Test the tool loop detection logic."""

    def test_single_failure_no_loop(self):
        detector = create_detector()
        # One failure should not trigger
        detector.observe("memory", {"action": "replace"}, json.dumps({"success": False, "error": "oops"}))
        assert detector.get_stats()["failure_counts"]["memory"] == 1

    def test_two_failures_no_loop(self):
        detector = create_detector()
        detector.observe("memory", {"action": "replace"}, json.dumps({"success": False, "error": "oops"}))
        detector.observe("memory", {"action": "replace"}, json.dumps({"success": False, "error": "oops"}))
        # Two failures with same args — not yet at threshold
        assert detector.get_stats()["consecutive_failures"]["memory"] == 2

    def test_three_identical_failures_triggers_loop(self):
        detector = create_detector()
        args = {"action": "replace", "old_text": "foo", "content": "bar"}

        detector.observe("memory", args, json.dumps({"success": False, "error": "first"}))
        detector.observe("memory", args, json.dumps({"success": False, "error": "second"}))

        with pytest.raises(ToolLoopError) as exc_info:
            detector.observe("memory", args, json.dumps({"success": False, "error": "third"}))

        assert "memory" in str(exc_info.value)
        assert "3" in str(exc_info.value) or "failed" in str(exc_info.value).lower()

    def test_different_args_no_loop(self):
        detector = create_detector()
        # Same tool, different args — should not trigger
        detector.observe("memory", {"action": "replace", "old_text": "a"}, json.dumps({"success": False}))
        detector.observe("memory", {"action": "replace", "old_text": "b"}, json.dumps({"success": False}))
        detector.observe("memory", {"action": "replace", "old_text": "c"}, json.dumps({"success": False}))
        # No exception
        assert detector.get_stats()["failure_counts"]["memory"] == 3

    def test_success_resets_counter(self):
        detector = create_detector()
        args = {"action": "replace", "old_text": "foo"}

        detector.observe("memory", args, json.dumps({"success": False, "error": "oops"}))
        detector.observe("memory", args, json.dumps({"success": True}))
        detector.observe("memory", args, json.dumps({"success": False, "error": "oops2"}))

        # Only 1 consecutive failure after success reset
        assert detector.get_stats()["consecutive_failures"]["memory"] == 1

    def test_total_failures_triggers_loop(self):
        detector = create_detector()
        # 5 different failures should trigger total-failure guard
        for i in range(4):
            detector.observe(
                "memory",
                {"action": "replace", "old_text": f"text{i}"},
                json.dumps({"success": False, "error": f"fail{i}"}),
            )

        with pytest.raises(ToolLoopError) as exc_info:
            detector.observe(
                "memory",
                {"action": "replace", "old_text": "text4"},
                json.dumps({"success": False, "error": "fail4"}),
            )

        assert "memory" in str(exc_info.value)


class TestMemoryToolValidator:
    """Test the memory tool validation logic."""

    def test_valid_memory_replace(self):
        validator = create_validator()
        args = {
            "action": "replace",
            "old_text": "original content",
            "content": "new content",
            "target": "memory",
        }
        valid, error = validator.validate(args)
        assert valid is True
        assert error == ""

    def test_truncated_artifact_rejected(self):
        validator = create_validator()
        args = {
            "action": "replace",
            "old_text": "[truncated]",
            "content": "new content",
            "target": "memory",
        }
        valid, error = validator.validate(args)
        assert valid is False
        assert "display artifact" in error.lower()

    def test_missing_required_params(self):
        validator = create_validator()
        args = {
            "action": "replace",
            "target": "memory",
            # Missing old_text and content
        }
        valid, error = validator.validate(args)
        assert valid is False
        assert "missing" in error.lower()

    def test_invalid_target(self):
        validator = create_validator()
        args = {
            "action": "add",
            "content": "new content",
            "target": "invalid_target",
        }
        valid, error = validator.validate(args)
        assert valid is False
        assert "target" in error.lower()

    def test_valid_add(self):
        validator = create_validator()
        args = {
            "action": "add",
            "content": "new memory",
            "target": "user",
        }
        valid, error = validator.validate(args)
        assert valid is True


class TestTaskStatePreserver:
    """Test task state preservation logic."""

    def test_set_and_build_message(self):
        preserver = create_preserver()
        preserver.set_task("Please refactor the auth module", "Refactor auth.py")

        msg = preserver.build_preservation_message()
        assert msg is not None
        assert msg["role"] == "system"
        assert "[TASK_STATE_PRESERVE]" in msg["content"]
        assert "refactor the auth module" in msg["content"]
        assert "Refactor auth.py" in msg["content"]

    def test_extract_from_messages(self):
        preserver = create_preserver()
        msg = {
            "role": "system",
            "content": (
                "[TASK_STATE_PRESERVE]\n"
                "Original user request: Build a login form\n"
                "Current objective: Create HTML login form\n"
                "Task hash: abc123\n"
                "This message must be preserved..."
            ),
        }

        recovered = preserver.extract_from_messages([msg])
        assert recovered is True
        assert preserver.get_task_summary() == "Create HTML login form"

    def test_no_task_returns_none(self):
        preserver = create_preserver()
        assert preserver.build_preservation_message() is None
        assert preserver.get_task_summary() is None


class TestGuardrailManager:
    """Test the integrated guardrail manager."""

    def test_full_flow_no_issues(self):
        mgr = GuardrailManager()
        mgr.set_task("Do something simple")

        # Simulate a successful tool call
        mgr.pre_tool_call("read_file", {"path": "/tmp/test"})
        mgr.post_tool_call("read_file", {"path": "/tmp/test"}, json.dumps({"success": True}))

        assert not mgr.is_halted()

    def test_memory_guardrail_blocks_invalid(self):
        mgr = GuardrailManager()
        mgr.set_task("Test task")

        with pytest.raises(MemoryValidationError) as exc_info:
            mgr.pre_tool_call("memory", {
                "action": "replace",
                "old_text": "[truncated]",
                "content": "new",
                "target": "memory",
            })

        assert "display artifact" in str(exc_info.value)

    def test_loop_detection_halts(self):
        mgr = GuardrailManager()
        mgr.set_task("Test task")

        args = {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"}

        # Pre-call should succeed
        mgr.pre_tool_call("memory", args)
        mgr.post_tool_call("memory", args, json.dumps({"success": False, "error": "fail1"}))

        mgr.pre_tool_call("memory", args)
        mgr.post_tool_call("memory", args, json.dumps({"success": False, "error": "fail2"}))

        mgr.pre_tool_call("memory", args)
        with pytest.raises(ToolLoopError):
            mgr.post_tool_call("memory", args, json.dumps({"success": False, "error": "fail3"}))

        assert mgr.is_halted()

    def test_halted_prevents_further_calls(self):
        mgr = GuardrailManager()
        mgr.set_task("Test task")

        # Trigger halt
        args = {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"}
        for _ in range(3):
            try:
                mgr.pre_tool_call("memory", args)
                mgr.post_tool_call("memory", args, json.dumps({"success": False, "error": "x"}))
            except ToolLoopError:
                break

        assert mgr.is_halted()

        # Next pre_tool_call should raise immediately
        with pytest.raises(ToolLoopError):
            mgr.pre_tool_call("memory", args)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
