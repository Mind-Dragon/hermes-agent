"""Agent Loop Guardrails — integration layer for loop prevention.

This module provides the glue code to integrate the three guardrail
components (tool_loop_detector, memory_tool_validator, task_state_preserver)
into the existing agent loop without heavy refactoring.

Usage in run_agent.py:
    from agent.agent_loop_guardrails import GuardrailManager

    # In AIAgent.__init__:
    self._guardrails = GuardrailManager()

    # In run_conversation(), after building user message:
    self._guardrails.set_task(user_message)

    # In the tool execution path, before/after handle_function_call:
    self._guardrails.pre_tool_call(tool_name, args)
    result = handle_function_call(...)
    self._guardrails.post_tool_call(tool_name, args, result)
"""

import json
import logging
from typing import Dict, Any, Optional

from agent.tool_loop_detector import ToolLoopDetector, ToolLoopError, create_detector
from agent.memory_tool_validator import MemoryToolValidator, MemoryValidationError, create_validator
from agent.task_state_preserver import TaskStatePreserver, create_preserver

logger = logging.getLogger(__name__)


class GuardrailManager:
    """Orchestrates all loop-prevention guardrails for a single agent session."""

    MAX_AUTONOMOUS_RECOVERY_ATTEMPTS = 1

    def __init__(self):
        self._loop_detector = create_detector()
        self._memory_validator = create_validator()
        self._task_preserver = create_preserver()
        self._halt_reason: Optional[str] = None
        self._recovery_prompt: Optional[str] = None
        self._blocked_tools: set[str] = set()
        self._recovery_attempts = 0

    # ------------------------------------------------------------------
    # Task state preservation
    # ------------------------------------------------------------------

    def set_task(self, user_request: str, objective: Optional[str] = None) -> None:
        """Record the user's original request at conversation start."""
        self._task_preserver.set_task(user_request, objective)

    def get_task_message(self) -> Optional[Dict[str, str]]:
        """Get a protected system message for task state preservation."""
        return self._task_preserver.build_preservation_message()

    def recover_task(self, messages: list) -> bool:
        """Try to recover task state from existing message history."""
        return self._task_preserver.extract_from_messages(messages)

    def get_task_summary(self) -> Optional[str]:
        """Return current task summary for status display."""
        return self._task_preserver.get_task_summary()

    # ------------------------------------------------------------------
    # Tool call guardrails
    # ------------------------------------------------------------------

    def pre_tool_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Validate tool call BEFORE execution.

        Raises MemoryValidationError for invalid memory tool calls.
        Raises ToolLoopError if a loop has already been detected.
        """
        # Check if we've already halted
        if self._halt_reason:
            raise ToolLoopError(
                tool_name=tool_name,
                loop_count=0,
                last_error=self._halt_reason,
                suggestion="Agent has already halted due to a previous error. Please start a new task or ask the user for guidance.",
            )

        if tool_name in self._blocked_tools:
            raise RuntimeError(
                f"Temporary guardrail block: do not call {tool_name} again yet. "
                "Recover with a different strategy first."
            )

        # Special validation for memory tool
        if tool_name == "memory":
            is_valid, error = self._memory_validator.validate(args)
            if not is_valid:
                logger.warning("Memory tool validation failed: %s", error)
                raise MemoryValidationError(
                    f"Invalid memory tool call: {error}. "
                    f"Please read the memory first to verify exact stored text, "
                    f"then retry with correct parameters."
                )

    def post_tool_call(self, tool_name: str, args: Dict[str, Any], result: str) -> None:
        """Observe tool result AFTER execution.

        Raises ToolLoopError if this call completes a detected loop pattern.
        """
        self._loop_detector.observe(tool_name, args, result)

    def try_autonomous_recovery(self, loop_error: ToolLoopError) -> bool:
        """Convert a recoverable guardrail halt into one API-only retry plan."""
        if (
            not getattr(loop_error, "recoverable", False)
            or not getattr(loop_error, "recovery_prompt", None)
            or self._recovery_attempts >= self.MAX_AUTONOMOUS_RECOVERY_ATTEMPTS
        ):
            self._halt_reason = str(loop_error)
            return False

        self._recovery_attempts += 1
        self._halt_reason = None
        self._recovery_prompt = loop_error.recovery_prompt
        self._blocked_tools = set(loop_error.blocked_tools or [])
        logger.warning(
            "Guardrail recovery armed (attempt %d/%d, blocked_tools=%s, failure_kind=%s)",
            self._recovery_attempts,
            self.MAX_AUTONOMOUS_RECOVERY_ATTEMPTS,
            sorted(self._blocked_tools),
            getattr(loop_error, "failure_kind", "unknown"),
        )
        return True

    def build_recovery_message(self) -> Optional[Dict[str, str]]:
        """Return an API-only system message guiding a one-shot recovery."""
        if not self._recovery_prompt:
            return None
        return {"role": "system", "content": self._recovery_prompt}

    def filter_tools_for_api(self, tools: Optional[list]) -> Optional[list]:
        """Temporarily hide blocked tools during a recovery attempt."""
        if not tools or not self._blocked_tools:
            return tools
        return [
            tool for tool in tools
            if tool.get("function", {}).get("name") not in self._blocked_tools
        ]

    def clear_recovery(self) -> None:
        """Clear any pending autonomous recovery state after a successful pivot."""
        self._recovery_prompt = None
        self._blocked_tools.clear()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return combined statistics from all guardrails."""
        return {
            "loop_detector": self._loop_detector.get_stats(),
            "memory_validator": self._memory_validator.get_stats(),
            "task_preserver": self._task_preserver.get_stats(),
            "halt_reason": self._halt_reason,
            "recovery_attempts": self._recovery_attempts,
            "blocked_tools": sorted(self._blocked_tools),
            "recovery_active": bool(self._recovery_prompt),
        }

    def is_halted(self) -> bool:
        """Return True if the guardrails have triggered a halt."""
        return self._halt_reason is not None
