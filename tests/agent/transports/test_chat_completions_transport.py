"""Regression tests for OpenAI-compatible chat-completions transport."""

from agent.transports.chat_completions import ChatCompletionsTransport


def test_minimax_highspeed_coalesces_multiple_system_messages_and_strips_internal_keys():
    transport = ChatCompletionsTransport()
    messages = [
        {"role": "system", "content": "base system"},
        {
            "role": "system",
            "content": "[TASK_STATE_PRESERVE]\nOriginal user request: inspect logs",
            "_task_state": {"original_request": "inspect logs"},
        },
        {"role": "user", "content": "Do the task"},
    ]

    kwargs = transport.build_kwargs(
        model="MiniMax-M2.7-highspeed",
        messages=messages,
    )

    assert [msg["role"] for msg in kwargs["messages"]] == ["system", "user"]
    assert kwargs["messages"][0]["content"] == (
        "base system\n\n"
        "[TASK_STATE_PRESERVE]\nOriginal user request: inspect logs"
    )
    assert "_task_state" not in kwargs["messages"][0]
    assert "_task_state" not in kwargs["messages"][1]
    # Provider normalization must not mutate persisted conversation history.
    assert [msg["role"] for msg in messages] == ["system", "system", "user"]
    assert "_task_state" in messages[1]


def test_non_highspeed_chat_keeps_multiple_system_messages_but_strips_internal_keys():
    transport = ChatCompletionsTransport()
    messages = [
        {"role": "system", "content": "base system"},
        {
            "role": "system",
            "content": "task state",
            "_task_state": {"original_request": "inspect logs"},
        },
        {"role": "user", "content": "Do the task"},
    ]

    kwargs = transport.build_kwargs(
        model="MiniMax-M2.7",
        messages=messages,
    )

    assert [msg["role"] for msg in kwargs["messages"]] == ["system", "system", "user"]
    assert all("_task_state" not in msg for msg in kwargs["messages"])
    assert "_task_state" in messages[1]


def test_highspeed_coalescing_keeps_qwen_inplace_prep_from_mutating_history():
    transport = ChatCompletionsTransport()
    messages = [
        {"role": "system", "content": "base system"},
        {"role": "system", "content": "task state"},
        {"role": "user", "content": "Do the task"},
    ]

    def mutate_in_place(prepared):
        prepared[-1]["content"] = "mutated by qwen prep"

    kwargs = transport.build_kwargs(
        model="MiniMax-M2.7-highspeed",
        messages=messages,
        is_qwen_portal=True,
        qwen_prepare_inplace_fn=mutate_in_place,
    )

    assert kwargs["messages"][-1]["content"] == "mutated by qwen prep"
    assert messages[-1]["content"] == "Do the task"
