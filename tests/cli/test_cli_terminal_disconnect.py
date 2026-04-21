"""Regression tests for classic CLI terminal-disconnect shutdown handling."""

import importlib
import os
import sys
from unittest.mock import MagicMock, Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def cli_mod():
    """Import ``cli`` with prompt_toolkit stubbed out for lightweight unit tests."""
    clean_env = {"LLM_MODEL": "", "HERMES_MAX_ITERATIONS": ""}
    prompt_toolkit_stubs = {
        "prompt_toolkit": MagicMock(),
        "prompt_toolkit.history": MagicMock(),
        "prompt_toolkit.styles": MagicMock(),
        "prompt_toolkit.patch_stdout": MagicMock(),
        "prompt_toolkit.application": MagicMock(),
        "prompt_toolkit.layout": MagicMock(),
        "prompt_toolkit.layout.processors": MagicMock(),
        "prompt_toolkit.filters": MagicMock(),
        "prompt_toolkit.layout.dimension": MagicMock(),
        "prompt_toolkit.layout.menus": MagicMock(),
        "prompt_toolkit.widgets": MagicMock(),
        "prompt_toolkit.key_binding": MagicMock(),
        "prompt_toolkit.completion": MagicMock(),
        "prompt_toolkit.formatted_text": MagicMock(),
        "prompt_toolkit.auto_suggest": MagicMock(),
    }

    from unittest.mock import patch

    with patch.dict(sys.modules, prompt_toolkit_stubs), patch.dict("os.environ", clean_env, clear=False):
        import cli as mod

        yield importlib.reload(mod)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (BrokenPipeError(), True),
        (OSError(5, "Input/output error"), True),
        (OSError(9, "Bad file descriptor"), True),
        (ValueError("I/O operation on closed file"), True),
        (RuntimeError("aclose(): asynchronous generator is already running"), False),
        (OSError(1, "Operation not permitted"), False),
        (None, False),
    ],
)
def test_is_terminal_disconnect_error(cli_mod, exc, expected):
    assert cli_mod._is_terminal_disconnect_error(exc) is expected


def test_should_suppress_asyncio_exception_for_terminal_disconnect(cli_mod):
    loop = Mock()
    context = {"exception": OSError(5, "Input/output error")}
    assert cli_mod._should_suppress_cli_asyncio_exception(loop, context) is True


def test_should_suppress_asyncio_exception_for_asyncgen_close_race(cli_mod):
    loop = Mock()
    context = {"exception": RuntimeError("aclose(): asynchronous generator is already running")}
    assert cli_mod._should_suppress_cli_asyncio_exception(loop, context) is True


def test_should_suppress_pending_prompt_toolkit_task_noise(cli_mod):
    loop = Mock()
    context = {
        "message": "Task was destroyed but it is pending!",
        "task": "<Task pending coro=<run_in_terminal.<locals>.run() done>>",
    }
    assert cli_mod._should_suppress_cli_asyncio_exception(loop, context) is True


def test_should_not_suppress_unrelated_asyncio_exception(cli_mod):
    loop = Mock()
    context = {"exception": RuntimeError("boom")}
    assert cli_mod._should_suppress_cli_asyncio_exception(loop, context) is False


def test_request_cli_exit_on_signal_exits_app_without_keyboardinterrupt(cli_mod, monkeypatch):
    app = Mock(is_running=True)
    agent = Mock()
    monkeypatch.setenv("HERMES_SIGTERM_GRACE", "0")

    exited = cli_mod._request_cli_exit_on_signal(app, 1, agent=agent, agent_running=True)

    assert exited is True
    agent.interrupt.assert_called_once_with("received signal 1")
    app.exit.assert_called_once()
    assert isinstance(app.exit.call_args.kwargs["exception"], EOFError)


def test_request_cli_exit_on_signal_falls_back_when_app_not_running(cli_mod, monkeypatch):
    app = Mock(is_running=False)
    agent = Mock()
    monkeypatch.setenv("HERMES_SIGTERM_GRACE", "0")

    exited = cli_mod._request_cli_exit_on_signal(app, 15, agent=agent, agent_running=True)

    assert exited is False
    agent.interrupt.assert_called_once_with("received signal 15")
    app.exit.assert_not_called()


def test_request_cli_exit_on_signal_still_exits_when_interrupt_fails(cli_mod, monkeypatch):
    app = Mock(is_running=True)
    agent = Mock()
    agent.interrupt.side_effect = RuntimeError("boom")
    monkeypatch.setenv("HERMES_SIGTERM_GRACE", "0")

    exited = cli_mod._request_cli_exit_on_signal(app, 15, agent=agent, agent_running=True)

    assert exited is True
    agent.interrupt.assert_called_once_with("received signal 15")
    app.exit.assert_called_once()
    assert isinstance(app.exit.call_args.kwargs["exception"], EOFError)
