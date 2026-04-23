"""
Integration test harness for agent loop guardrails.

Tests 4 scenarios with pass/fail variants:
1. Tool loop detection (identical failures)
2. Memory validation (truncated artifacts, missing params)
3. Task state preservation (survives compaction)
4. Guardrail halt (prevents further calls after detection)

Usage: python test_guardrails_integration.py
"""

import json
import sys
import time
from typing import Dict, Any, List

from agent.tool_loop_detector import create_detector, ToolLoopError
from agent.memory_tool_validator import create_validator, MemoryValidationError
from agent.task_state_preserver import create_preserver
from agent.agent_loop_guardrails import GuardrailManager


class ScenarioRunner:
    __test__ = False

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def run(self, name: str, fn, should_pass: bool = True):
        try:
            fn()
            if should_pass:
                self.passed += 1
                self.results.append(f"  PASS: {name}")
            else:
                self.failed += 1
                self.results.append(f"  FAIL: {name} (expected failure but passed)")
        except Exception as e:
            if not should_pass:
                self.passed += 1
                self.results.append(f"  EXPECTED FAIL: {name}: {type(e).__name__}")
            else:
                self.failed += 1
                self.results.append(f"  FAIL: {name}: {type(e).__name__}: {e}")

    def report(self):
        print("\n".join(self.results))
        print(f"\nTotal: {self.passed + self.failed}, Passed: {self.passed}, Failed: {self.failed}")
        return self.failed == 0


def test_scenario_1_tool_loop_detection():
    """Scenario 1: Tool loop detection — identical consecutive failures."""
    runner = ScenarioRunner()

    # Pass case 1a: Single failure does not trigger
    def pass_1a():
        d = create_detector()
        d.observe("memory", {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"},
                   json.dumps({"success": False, "error": "oops"}))
        assert d.get_stats()["consecutive_failures"]["memory"] == 1

    # Pass case 1b: Different args do not trigger (stay under 5 total)
    def pass_1b():
        d = create_detector()
        for i in range(4):  # 4 failures with different args — under MAX_TOTAL_FAILURES=5
            d.observe("memory", {"action": "replace", "old_text": f"text{i}", "content": "bar", "target": "memory"},
                       json.dumps({"success": False, "error": str(i)}))
        assert d.get_stats()["failure_counts"]["memory"] == 4

    # Pass case 1c: Success resets counter
    def pass_1c():
        d = create_detector()
        args = {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"}
        d.observe("memory", args, json.dumps({"success": False, "error": "1"}))
        d.observe("memory", args, json.dumps({"success": True}))
        d.observe("memory", args, json.dumps({"success": False, "error": "2"}))
        assert d.get_stats()["consecutive_failures"]["memory"] == 1

    # Pass case 1d: Mixed tools don't interfere
    def pass_1d():
        d = create_detector()
        args = {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"}
        d.observe("memory", args, json.dumps({"success": False, "error": "1"}))
        d.observe("read_file", {"path": "/tmp/x"}, json.dumps({"success": False, "error": "x"}))
        d.observe("memory", args, json.dumps({"success": False, "error": "2"}))
        # memory has 2 consecutive, read_file has 1
        assert d.get_stats()["consecutive_failures"]["memory"] == 2
        assert d.get_stats()["consecutive_failures"]["read_file"] == 1

    # Fail case 1e: 3 identical failures trigger loop
    def fail_1e():
        d = create_detector()
        args = {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"}
        d.observe("memory", args, json.dumps({"success": False, "error": "1"}))
        d.observe("memory", args, json.dumps({"success": False, "error": "2"}))
        d.observe("memory", args, json.dumps({"success": False, "error": "3"}))

    # Fail case 1f: 5 total failures trigger loop even with varying args
    def fail_1f():
        d = create_detector()
        for i in range(6):
            d.observe("memory", {"action": "replace", "old_text": f"text{i}", "content": "bar", "target": "memory"},
                       json.dumps({"success": False, "error": str(i)}))

    runner.run("1a: single failure no loop", pass_1a)
    runner.run("1b: different args no loop", pass_1b)
    runner.run("1c: success resets counter", pass_1c)
    runner.run("1d: mixed tools no interference", pass_1d)
    runner.run("1e: 3 identical failures trigger", fail_1e, should_pass=False)
    runner.run("1f: 5 total failures trigger", fail_1f, should_pass=False)

    assert runner.report()


def test_scenario_2_memory_validation():
    """Scenario 2: Memory tool validation — prevents malformed calls."""
    runner = ScenarioRunner()

    # Pass case 2a: Valid replace passes
    def pass_2a():
        v = create_validator()
        valid, err = v.validate({"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"})
        assert valid and err == ""

    # Pass case 2b: Valid add passes
    def pass_2b():
        v = create_validator()
        valid, err = v.validate({"action": "add", "content": "new memory", "target": "user"})
        assert valid and err == ""

    # Pass case 2c: Valid remove passes
    def pass_2c():
        v = create_validator()
        valid, err = v.validate({"action": "remove", "old_text": "foo", "target": "memory"})
        assert valid and err == ""

    # Pass case 2d: Unknown action passes through
    def pass_2d():
        v = create_validator()
        valid, err = v.validate({"action": "unknown_action", "target": "memory"})
        assert valid  # unknown actions are allowed to fail naturally

    # Fail case 2e: Truncated artifact rejected (returns False, not raises)
    def pass_2e():
        v = create_validator()
        valid, err = v.validate({"action": "replace", "old_text": "[truncated]", "content": "bar", "target": "memory"})
        assert not valid  # Should reject

    # Fail case 2f: Missing required params rejected
    def pass_2f():
        v = create_validator()
        valid, err = v.validate({"action": "replace", "target": "memory"})
        assert not valid  # Should reject

    # Fail case 2g: Invalid target rejected
    def pass_2g():
        v = create_validator()
        valid, err = v.validate({"action": "add", "content": "x", "target": "invalid"})
        assert not valid  # Should reject

    # Fail case 2h: Content with artifact rejected
    def pass_2h():
        v = create_validator()
        valid, err = v.validate({"action": "add", "content": "[...]", "target": "memory"})
        assert not valid  # Should reject

    runner.run("2a: valid replace passes", pass_2a)
    runner.run("2b: valid add passes", pass_2b)
    runner.run("2c: valid remove passes", pass_2c)
    runner.run("2d: unknown action passes", pass_2d)
    runner.run("2e: truncated artifact rejected", pass_2e)
    runner.run("2f: missing params rejected", pass_2f)
    runner.run("2g: invalid target rejected", pass_2g)
    runner.run("2h: content artifact rejected", pass_2h)

    assert runner.report()


def test_scenario_3_task_preservation():
    """Scenario 3: Task state preservation — survives message history."""
    runner = ScenarioRunner()

    # Pass case 3a: Set and build message
    def pass_3a():
        p = create_preserver()
        p.set_task("Refactor auth module")
        msg = p.build_preservation_message()
        assert msg is not None
        assert msg["role"] == "system"
        assert "[TASK_STATE_PRESERVE]" in msg["content"]
        assert "Refactor auth module" in msg["content"]

    # Pass case 3b: Extract from messages
    def pass_3b():
        p = create_preserver()
        msg = {
            "role": "system",
            "content": (
                "[TASK_STATE_PRESERVE]\n"
                "Original user request: Build a login form\n"
                "Current objective: Create HTML login form\n"
                "Task hash: abc123\n"
            ),
        }
        recovered = p.extract_from_messages([msg])
        assert recovered
        assert p.get_task_summary() == "Create HTML login form"

    # Pass case 3c: Message survives in list
    def pass_3c():
        p = create_preserver()
        p.set_task("Test task", "Do testing")
        msg = p.build_preservation_message()
        messages = [msg, {"role": "user", "content": "hello"}]
        # Simulate compaction removing user message
        messages = [msg]  # Only system message remains
        recovered = p.extract_from_messages(messages)
        assert recovered
        assert p.get_task_summary() == "Do testing"

    # Pass case 3d: No task returns None safely
    def pass_3d():
        p = create_preserver()
        assert p.build_preservation_message() is None
        assert p.get_task_summary() is None

    # Fail case 3e: Missing marker doesn't extract
    def fail_3e():
        p = create_preserver()
        msg = {"role": "system", "content": "Just a normal system message"}
        recovered = p.extract_from_messages([msg])
        assert recovered  # Should be False

    # Fail case 3f: Wrong role doesn't extract
    def fail_3f():
        p = create_preserver()
        msg = {"role": "user", "content": "[TASK_STATE_PRESERVE]\nOriginal user request: X"}
        recovered = p.extract_from_messages([msg])
        assert recovered  # Should be False (wrong role)

    runner.run("3a: set and build message", pass_3a)
    runner.run("3b: extract from messages", pass_3b)
    runner.run("3c: survives compaction", pass_3c)
    runner.run("3d: no task returns None", pass_3d)
    runner.run("3e: missing marker no extract", fail_3e, should_pass=False)
    runner.run("3f: wrong role no extract", fail_3f, should_pass=False)

    assert runner.report()


def test_scenario_4_guardrail_manager():
    """Scenario 4: Integrated GuardrailManager — full workflow."""
    runner = ScenarioRunner()

    # Pass case 4a: Normal flow no halt
    def pass_4a():
        mgr = GuardrailManager()
        mgr.set_task("Test task")
        mgr.pre_tool_call("read_file", {"path": "/tmp/test"})
        mgr.post_tool_call("read_file", {"path": "/tmp/test"}, json.dumps({"success": True}))
        assert not mgr.is_halted()

    # Pass case 4b: Memory validation blocks invalid
    def pass_4b():
        mgr = GuardrailManager()
        mgr.set_task("Test task")
        try:
            mgr.pre_tool_call("memory", {"action": "replace", "old_text": "[truncated]", "content": "x", "target": "memory"})
            assert False  # Should have raised
        except MemoryValidationError:
            pass  # Expected
        assert not mgr.is_halted()  # Validation error doesn't halt

    # Pass case 4c: Task summary available
    def pass_4c():
        mgr = GuardrailManager()
        mgr.set_task("Build a login form", "Create HTML form")
        assert mgr.get_task_summary() == "Create HTML form"

    # Pass case 4d: Stats accessible
    def pass_4d():
        mgr = GuardrailManager()
        mgr.set_task("Test")
        stats = mgr.get_stats()
        assert "loop_detector" in stats
        assert "memory_validator" in stats
        assert "task_preserver" in stats

    # Fail case 4e: Loop detection halts
    def fail_4e():
        mgr = GuardrailManager()
        mgr.set_task("Test")
        args = {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"}
        for i in range(3):
            mgr.pre_tool_call("memory", args)
            mgr.post_tool_call("memory", args, json.dumps({"success": False, "error": str(i)}))
        assert mgr.is_halted()

    # Fail case 4f: Halted prevents further calls
    def fail_4f():
        mgr = GuardrailManager()
        mgr.set_task("Test")
        args = {"action": "replace", "old_text": "foo", "content": "bar", "target": "memory"}
        for i in range(3):
            try:
                mgr.pre_tool_call("memory", args)
                mgr.post_tool_call("memory", args, json.dumps({"success": False, "error": str(i)}))
            except ToolLoopError:
                break
        assert mgr.is_halted()
        # Next call should raise immediately
        mgr.pre_tool_call("memory", args)

    # Fail case 4g: Multiple tools tracked separately
    def fail_4g():
        mgr = GuardrailManager()
        mgr.set_task("Test")
        # 3 failures on read_file
        for i in range(3):
            mgr.pre_tool_call("read_file", {"path": "/tmp/x"})
            mgr.post_tool_call("read_file", {"path": "/tmp/x"}, json.dumps({"success": False, "error": str(i)}))
        # 3 failures on memory
        for i in range(3):
            mgr.pre_tool_call("memory", {"action": "replace", "old_text": "a", "content": "b", "target": "memory"})
            mgr.post_tool_call("memory", {"action": "replace", "old_text": "a", "content": "b", "target": "memory"}, json.dumps({"success": False, "error": str(i)}))
        # Should be halted
        assert mgr.is_halted()

    # Fail case 4h: Task state message exists when task is set
    def pass_4h():
        mgr = GuardrailManager()
        mgr.set_task("Original request", "Current objective")
        msg = mgr.get_task_message()
        assert msg is not None  # Should return a valid message

    runner.run("4a: normal flow no halt", pass_4a)
    runner.run("4b: memory validation blocks", pass_4b)
    runner.run("4c: task summary available", pass_4c)
    runner.run("4d: stats accessible", pass_4d)
    runner.run("4e: loop detection halts", fail_4e, should_pass=False)
    runner.run("4f: halted prevents calls", fail_4f, should_pass=False)
    runner.run("4g: multiple tools tracked", fail_4g, should_pass=False)
    runner.run("4h: task message exists", pass_4h)

    assert runner.report()


if __name__ == "__main__":
    print("=" * 60)
    print("AGENT LOOP GUARDRAIL INTEGRATION TESTS")
    print("=" * 60)

    all_pass = True

    print("\n--- Scenario 1: Tool Loop Detection ---")
    try:
        test_scenario_1_tool_loop_detection()
    except (AssertionError, Exception) as e:
        print(f"FAILED: {e}")
        all_pass = False

    print("\n--- Scenario 2: Memory Validation ---")
    try:
        test_scenario_2_memory_validation()
    except (AssertionError, Exception) as e:
        print(f"FAILED: {e}")
        all_pass = False

    print("\n--- Scenario 3: Task Preservation ---")
    try:
        test_scenario_3_task_preservation()
    except (AssertionError, Exception) as e:
        print(f"FAILED: {e}")
        all_pass = False

    print("\n--- Scenario 4: GuardrailManager Integration ---")
    try:
        test_scenario_4_guardrail_manager()
    except (AssertionError, Exception) as e:
        print(f"FAILED: {e}")
        all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
