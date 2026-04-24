"""
Pure guardrail primitives for tool calls.

This module provides utility functions for:
- Canonicalizing tool call arguments (sorted compact JSON)
- Detecting tool failures based on various heuristics
- Tracking repeated identical failed tool calls
- Validating memory tool arguments (rejecting display artifacts)

No runtime behavior changes; this is a pure library.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


def canonicalize_tool_args(args: Dict[str, Any]) -> str:
    """
    Canonicalize tool call arguments with sorted compact JSON.

    Args:
        args: Dictionary of tool arguments.

    Returns:
        Compact JSON string with keys sorted alphabetically.

    Raises:
        TypeError: If args is not a dict.
    """
    if not isinstance(args, dict):
        raise TypeError(f"args must be a dict, got {type(args).__name__}")
    # Ensure ASCII is disabled to preserve Unicode characters.
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_args_hash(canonical_args: str) -> str:
    """
    Compute a deterministic hash of canonical args string.

    Uses SHA-256 and returns hex digest.

    Args:
        canonical_args: The canonical JSON string from canonicalize_tool_args.

    Returns:
        64-character hex string.
    """
    return hashlib.sha256(canonical_args.encode("utf-8")).hexdigest()


def detect_tool_failure(tool_name: str, result: Optional[str]) -> bool:
    """
    Detect whether a tool result indicates failure.

    Consistent with existing display semantics where practical.
    Rules:
    - JSON 'success: false' -> failure
    - JSON non-empty 'error' -> failure
    - Terminal nonzero exit_code -> failure
    - Python exception-shaped strings (Traceback, Error:) -> failure
    - Obvious error strings compatible with display heuristics -> failure
    - Empty successful content / empty reads are NOT failures

    Args:
        tool_name: Name of the tool (e.g., "terminal", "memory").
        result: Tool result string (may be JSON or plain text).

    Returns:
        True if failure detected, False otherwise.
    """
    if result is None:
        return False

    # Try to parse as JSON
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError, ValueError):
        data = None

    if isinstance(data, dict):
        # Memory-specific: "full" detection (existing display semantics).
        # Check before generic success:false so this branch stays reachable if
        # callers later add richer classification around memory capacity errors.
        if tool_name == "memory":
            error = data.get("error", "")
            if data.get("success") is False and isinstance(error, str) and "exceed the limit" in error:
                return True
        # JSON success: false
        if data.get("success") is False:
            return True
        # JSON non-empty error
        error = data.get("error")
        if error is not None and error != "":
            return True
        # JSON failed: true
        if data.get("failed") is True:
            return True
        # Terminal exit_code
        if tool_name == "terminal":
            exit_code = data.get("exit_code")
            if exit_code is not None and exit_code != 0:
                return True
        # If we parsed JSON and none of the above failure conditions matched,
        # treat as success (even if error field is empty).
        return False

    # Non-JSON detection
    # Python exception-shaped strings
    lower = result[:500].lower()
    if "traceback" in lower or lower.startswith("error:"):
        return True
    # Obvious error strings (existing display semantics).
    # Keep this intentionally conservative: plain text containing "failed" can
    # be a false positive (for example, "failed successfully"), but quoted
    # structured fields like "failed" are treated as errors.
    if '"error"' in lower or '"failed"' in lower or result.startswith("Error"):
        return True

    # Empty successful content / empty reads are NOT failures
    # (already covered by returning False)
    return False


@dataclass
class RepeatedFailureTracker:
    """
    Track consecutive identical failed tool calls by (tool_name, canonical_args_hash).

    Only one streak is active at a time: the current key and its count.
    A materially different (tool_name, args_hash) resets the previous streak
    and starts a new streak at 1. A success resets the current matching streak.

    Attributes:
        threshold: Number of identical failures before blocking (default 3).
    """
    threshold: int = 3
    _current_key: Optional[Tuple[str, str]] = None
    _current_count: int = 0

    def failure_count(self, tool_name: str, args_hash: str) -> int:
        """Return current failure count for the given tool and args hash,
        but only if it's the current key; otherwise 0."""
        if self._current_key == (tool_name, args_hash):
            return self._current_count
        return 0

    def record_failure(self, tool_name: str, args_hash: str) -> None:
        """Increment failure count for the given tool and args hash.
        If key matches current key, increment; otherwise set new key and count=1."""
        key = (tool_name, args_hash)
        if self._current_key == key:
            self._current_count += 1
        else:
            self._current_key = key
            self._current_count = 1

    def reset_on_success(self, tool_name: str, args_hash: str) -> None:
        """Reset failure count for the given tool and args hash on success,
        but only if it's the current key."""
        key = (tool_name, args_hash)
        if self._current_key == key:
            self._current_count = 0

    def should_block(self, tool_name: str, args_hash: str) -> bool:
        """Return True if failure count for this key meets threshold."""
        return self.failure_count(tool_name, args_hash) >= self.threshold


def memory_argument_policy(args: Dict[str, Any]) -> bool:
    """
    Pure memory argument policy rejecting display artifacts.

    Rejects old_text / content that contain display artifacts:
    - [truncated]
    - [...]
    - [cont]
    - [more]

    Handles non-string args cleanly without TypeError (returns False).

    Args:
        args: Dictionary of memory tool arguments (may contain 'content', 'old_text').

    Returns:
        True if arguments are acceptable (no display artifacts), False otherwise.
    """
    # List of artifact patterns (case-sensitive as they appear in output)
    artifacts = ["[truncated]", "[...]", "[cont]", "[more]"]

    for key in ("content", "old_text"):
        if key not in args:
            # Missing key is acceptable (optional parameter)
            continue
        value = args[key]
        if isinstance(value, str):
            for artifact in artifacts:
                if artifact in value:
                    return False
        else:
            # Non-string argument (e.g., int, list, None) is considered invalid
            # (memory tool expects string). Return False without raising TypeError.
            return False
    # All checks passed
    return True