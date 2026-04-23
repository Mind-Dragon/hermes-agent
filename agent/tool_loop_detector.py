"""Tool Loop Detector — prevents infinite retry loops in tool execution.

This module implements the detection heuristic from the crash RCA:
- Same tool call pattern repeats >3 times
- Each result contains `"success": false`
- No variation in arguments between calls

When detected, it raises ToolLoopError which the agent loop catches and
escalates to the user rather than continuing the loop.
"""

import json
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ToolLoopError(Exception):
    """Raised when a tool call loop is detected.

    Contains diagnostic information about the loop for the agent to report.
    """
    def __init__(self, tool_name: str, loop_count: int, last_error: str, suggestion: str):
        self.tool_name = tool_name
        self.loop_count = loop_count
        self.last_error = last_error
        self.suggestion = suggestion
        super().__init__(
            f"Tool loop detected: {tool_name} failed {loop_count} times consecutively. "
            f"Last error: {last_error}. {suggestion}"
        )


@dataclass
class ToolCallRecord:
    """Single tool call observation."""
    tool_name: str
    args_hash: str
    result_success: bool
    result_error: Optional[str] = None
    result_content: Optional[str] = None


class ToolLoopDetector:
    """Stateful detector that tracks recent tool calls and detects loops.

    Instantiate once per agent session and call observe() after each
    tool call. Raises ToolLoopError when a loop is detected.
    """

    # Detection thresholds
    MAX_CONSECUTIVE_FAILURES = 3  # After 3 identical failures, escalate
    MAX_TOTAL_FAILURES = 5        # After 5 total failures of same tool, escalate
    COMPARISON_WINDOW = 10        # Compare against last 10 calls

    def __init__(self):
        self._history: List[ToolCallRecord] = []
        self._failure_counts: Dict[str, int] = {}
        self._consecutive_failures: Dict[str, int] = {}
        self._last_args_hash: Dict[str, str] = {}

    def _hash_args(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Create a stable hash of tool arguments for comparison."""
        try:
            # Normalize: sort keys, compact JSON
            canonical = json.dumps(args, sort_keys=True, separators=(',', ':'))
        except (TypeError, ValueError):
            # Fallback for non-serializable args
            canonical = str(args)
        return hashlib.sha256(f"{tool_name}:{canonical}".encode()).hexdigest()[:16]

    def _extract_error(self, result: str) -> Optional[str]:
        """Extract error message from tool result JSON."""
        try:
            data = json.loads(result)
            # Explicit success: false
            if not data.get("success", True):
                return data.get("error", "Unknown error")
            # Many tools (read_file, etc.) return {error: "..."} without a
            # success flag — treat presence of an error key as failure.
            if "error" in data and data["error"]:
                return str(data["error"])
            return None
        except (json.JSONDecodeError, TypeError):
            # Non-JSON result — treat as success unless it contains "error"
            if isinstance(result, str) and "error" in result.lower() and len(result) < 500:
                return result
            return None

    def observe(self, tool_name: str, args: Dict[str, Any], result: str) -> None:
        """Record a tool call and check for loops.

        Args:
            tool_name: Name of the tool that was called
            args: Arguments passed to the tool
            result: JSON string result from the tool

        Raises:
            ToolLoopError: If a loop pattern is detected
        """
        args_hash = self._hash_args(tool_name, args)
        error = self._extract_error(result)
        success = error is None

        record = ToolCallRecord(
            tool_name=tool_name,
            args_hash=args_hash,
            result_success=success,
            result_error=error,
            result_content=result[:200] if not success else None,
        )
        self._history.append(record)

        # Keep window bounded
        if len(self._history) > self.COMPARISON_WINDOW * 2:
            self._history = self._history[-self.COMPARISON_WINDOW:]

        if not success:
            # Track failures per tool
            self._failure_counts[tool_name] = self._failure_counts.get(tool_name, 0) + 1
            self._consecutive_failures[tool_name] = self._consecutive_failures.get(tool_name, 0) + 1

            # Check for identical consecutive failures
            recent = [r for r in self._history if r.tool_name == tool_name][-self.MAX_CONSECUTIVE_FAILURES:]
            if len(recent) >= self.MAX_CONSECUTIVE_FAILURES:
                all_same_args = all(r.args_hash == recent[0].args_hash for r in recent)
                all_failed = all(not r.result_success for r in recent)

                if all_same_args and all_failed:
                    last_error = recent[-1].result_error or "Unknown error"
                    raise ToolLoopError(
                        tool_name=tool_name,
                        loop_count=len(recent),
                        last_error=last_error,
                        suggestion=(
                            f"The same {tool_name} call with identical arguments failed "
                            f"{len(recent)} times. Last error: {last_error}. "
                            f"Halting to prevent infinite loop. Please check the error "
                            f"and try a different approach, or ask the user for guidance."
                        ),
                    )

            # Check total failures (even with varying args)
            if self._failure_counts.get(tool_name, 0) >= self.MAX_TOTAL_FAILURES:
                recent_same = [r for r in self._history if r.tool_name == tool_name][-self.MAX_TOTAL_FAILURES:]
                last_error = recent_same[-1].result_error or "Unknown error"
                raise ToolLoopError(
                    tool_name=tool_name,
                    loop_count=self._failure_counts[tool_name],
                    last_error=last_error,
                    suggestion=(
                        f"{tool_name} has failed {self._failure_counts[tool_name]} times "
                        f"in this session. Last error: {last_error}. "
                        f"Halting to prevent resource waste. Consider using a different "
                        f"tool or asking the user for clarification."
                    ),
                )
        else:
            # Reset consecutive counter on success
            self._consecutive_failures[tool_name] = 0

    def get_stats(self) -> Dict[str, Any]:
        """Return current detection statistics for debugging."""
        return {
            "total_calls": len(self._history),
            "failure_counts": dict(self._failure_counts),
            "consecutive_failures": dict(self._consecutive_failures),
            "recent_tools": [r.tool_name for r in self._history[-5:]],
        }


def create_detector() -> ToolLoopDetector:
    """Factory function for creating a fresh detector."""
    return ToolLoopDetector()
