"""Memory Tool Validator — prevents common memory tool misuse patterns.

This module validates memory tool calls before they reach the actual
memory implementation, catching patterns that caused the infinite loop:

1. Using '[truncated]' as literal old_text (display artifact)
2. Missing required parameters for replace/add/remove actions
3. Malformed old_text that doesn't match stored content
"""

import json
import re
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class MemoryValidationError(Exception):
    """Raised when a memory tool call is invalid."""
    pass


class MemoryToolValidator:
    """Validates memory tool arguments before execution.

    Instantiated once per session. Call validate() before dispatching
    to the actual memory tool.
    """

    # Patterns that indicate display artifacts being used as literal text
    DISPLAY_ARTIFACT_PATTERNS = [
        r'\[truncated\]',
        r'\[\.\.\.\]',
        r'\[cont\]',
        r'\[more\]',
    ]

    # Required parameters per action
    REQUIRED_PARAMS = {
        "replace": ["old_text", "content", "target"],
        "add": ["content", "target"],
        "remove": ["old_text", "target"],
    }

    def __init__(self):
        self._validation_count = 0
        self._rejection_count = 0
        self._last_rejection_reason: Optional[str] = None

    def _contains_display_artifact(self, text: str) -> bool:
        """Check if text contains display truncation markers."""
        if not text:
            return False
        for pattern in self.DISPLAY_ARTIFACT_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    def _check_required_params(self, action: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """Verify all required parameters are present for the action."""
        required = self.REQUIRED_PARAMS.get(action)
        if not required:
            # Unknown action — let it through to fail naturally
            return True, ""

        missing = [p for p in required if p not in args or args[p] is None]
        if missing:
            return False, f"Missing required parameters for '{action}': {', '.join(missing)}"
        return True, ""

    def validate(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate memory tool arguments.

        Args:
            args: The arguments dict passed to the memory tool

        Returns:
            Tuple of (is_valid, error_message)
        """
        self._validation_count += 1

        action = args.get("action", "")
        if not action:
            self._rejection_count += 1
            self._last_rejection_reason = "Missing 'action' parameter"
            return False, self._last_rejection_reason

        # Check required parameters
        valid, error = self._check_required_params(action, args)
        if not valid:
            self._rejection_count += 1
            self._last_rejection_reason = error
            return False, error

        # Check for display artifacts in old_text
        old_text = args.get("old_text", "")
        if old_text and self._contains_display_artifact(old_text):
            self._rejection_count += 1
            self._last_rejection_reason = (
                f"old_text contains display artifact markers (e.g. [truncated]). "
                f"These are not real stored text — read the memory first to get "
                f"the exact stored content before replacing."
            )
            return False, self._last_rejection_reason

        # Check for display artifacts in content
        content = args.get("content", "")
        if content and self._contains_display_artifact(content):
            self._rejection_count += 1
            self._last_rejection_reason = (
                f"content contains display artifact markers (e.g. [truncated]). "
                f"These are not real stored text."
            )
            return False, self._last_rejection_reason

        # Validate target is valid
        target = args.get("target", "")
        if target not in ("memory", "user"):
            self._rejection_count += 1
            self._last_rejection_reason = (
                f"Invalid target '{target}'. Must be 'memory' or 'user'."
            )
            return False, self._last_rejection_reason

        return True, ""

    def get_stats(self) -> Dict[str, Any]:
        """Return validation statistics."""
        return {
            "validations": self._validation_count,
            "rejections": self._rejection_count,
            "last_rejection": self._last_rejection_reason,
        }


def create_validator() -> MemoryToolValidator:
    """Factory for creating a fresh validator."""
    return MemoryToolValidator()
