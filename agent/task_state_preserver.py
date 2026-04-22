"""Task State Preservation — prevents task loss during context compaction.

When context compaction removes the user's original request from the
conversation history, this module ensures the task definition survives
by embedding it in a protected message that compression won't remove.

The RCA showed that compaction removed 130 turns including the user's
actual request, leaving only "just get this done please" — which is
not a recoverable task description.
"""

import json
import hashlib
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


# Marker that identifies a protected task-state message
TASK_STATE_ROLE = "system"
TASK_STATE_MARKER = "[TASK_STATE_PRESERVE]"


class TaskStatePreserver:
    """Preserves task state across context compaction events.

    Embed the user's original request and current objective in a
    system-level message that context compression treats as protected
    (part of the system prompt, not the conversation body).
    """

    def __init__(self):
        self._original_request: Optional[str] = None
        self._current_objective: Optional[str] = None
        self._task_hash: Optional[str] = None
        self._preservation_count = 0

    def _hash_task(self, request: str, objective: str) -> str:
        """Create a hash of the task for deduplication."""
        return hashlib.sha256(
            f"{request}:{objective}".encode()
        ).hexdigest()[:12]

    def set_task(self, user_request: str, objective: Optional[str] = None) -> None:
        """Record the user's original request and current objective.

        Call this at the start of run_conversation() before any
        compaction can occur.
        """
        self._original_request = user_request
        self._current_objective = objective or user_request
        self._task_hash = self._hash_task(user_request, self._current_objective)
        logger.debug("Task state recorded: hash=%s", self._task_hash)

    def build_preservation_message(self) -> Optional[Dict[str, str]]:
        """Build a protected system message containing task state.

        Returns None if no task has been set.
        """
        if not self._original_request:
            return None

        self._preservation_count += 1

        content = (
            f"{TASK_STATE_MARKER}\n"
            f"Original user request: {self._original_request}\n"
        )
        if self._current_objective and self._current_objective != self._original_request:
            content += f"Current objective: {self._current_objective}\n"
        content += (
            f"Task hash: {self._task_hash}\n"
            f"This message must be preserved across all context compaction events. "
            f"If the conversation history is compressed, the agent must still know "
            f"what task it was asked to perform."
        )

        return {
            "role": TASK_STATE_ROLE,
            "content": content,
            "_task_state": True,  # Internal marker for compression logic
        }

    def extract_from_messages(self, messages: List[Dict[str, Any]]) -> bool:
        """Attempt to recover task state from existing messages.

        Call this after loading conversation history to see if a prior
        session preserved task state.

        Returns True if task state was recovered.
        """
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if TASK_STATE_MARKER in content and msg.get("role") == TASK_STATE_ROLE:
                # Extract original request
                lines = content.split("\n")
                for line in lines:
                    if line.startswith("Original user request: "):
                        self._original_request = line[len("Original user request: "):]
                    elif line.startswith("Current objective: "):
                        self._current_objective = line[len("Current objective: "):]
                    elif line.startswith("Task hash: "):
                        self._task_hash = line[len("Task hash: "):]

                if self._original_request:
                    logger.debug("Task state recovered from messages: hash=%s", self._task_hash)
                    return True
        return False

    def get_task_summary(self) -> Optional[str]:
        """Return a one-line summary of the current task for status display."""
        if not self._original_request:
            return None
        obj = self._current_objective or self._original_request
        # Truncate for display
        if len(obj) > 80:
            obj = obj[:77] + "..."
        return obj

    def get_stats(self) -> Dict[str, Any]:
        """Return preservation statistics."""
        return {
            "original_request": self._original_request,
            "current_objective": self._current_objective,
            "task_hash": self._task_hash,
            "preservation_count": self._preservation_count,
        }


def create_preserver() -> TaskStatePreserver:
    """Factory for creating a fresh preserver."""
    return TaskStatePreserver()
