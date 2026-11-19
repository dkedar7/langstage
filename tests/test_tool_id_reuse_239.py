"""gh #239: a tool call id repeated in a later turn keeps each call's own result.

Ids are only unique within one model response. The keyless demo agent gives every
call ``demo_lookup_1``, so History paired every call with the last result.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from langstage.conversations import transcript


def _call(query: str, call_id: str = "demo_lookup_1") -> dict:
    return {"name": "demo_lookup", "args": {"query": query}, "id": call_id}


def _calls(entries):
    return [c for e in entries for c in e.get("tool_calls", [])]


def test_a_reused_id_keeps_each_turns_result():
    messages = [
        HumanMessage("use a tool"),
        AIMessage("", tool_calls=[_call("first")]),
        ToolMessage("result one", tool_call_id="demo_lookup_1"),
        AIMessage("done one"),
        HumanMessage("use a tool again"),
        AIMessage("", tool_calls=[_call("second")]),
        ToolMessage("result two", tool_call_id="demo_lookup_1"),
        AIMessage("done two"),
    ]
    calls = _calls(transcript(messages))
    assert [(c["args"]["query"], c["status"], c.get("result")) for c in calls] == [
        ("first", "success", "result one"),
        ("second", "success", "result two"),
    ]


def test_a_later_call_with_a_reused_id_and_no_result_is_pending():
    # Turn 2 is waiting on an approval: its call must not borrow turn 1's result.
    messages = [
        HumanMessage("use a tool"),
        AIMessage("", tool_calls=[_call("first")]),
        ToolMessage("result one", tool_call_id="demo_lookup_1"),
        AIMessage("done one"),
        HumanMessage("use a tool again"),
        AIMessage("", tool_calls=[_call("second")]),
    ]
    first, second = _calls(transcript(messages))
    assert first["result"] == "result one"
    assert second["status"] == "pending" and "result" not in second


def test_parallel_calls_still_pair_by_id():
    messages = [
        HumanMessage("two at once"),
        AIMessage("", tool_calls=[_call("a", "c1"), _call("b", "c2")]),
        ToolMessage("for b", tool_call_id="c2"),
        ToolMessage("for a", tool_call_id="c1", status="error"),
        AIMessage("done"),
    ]
    a, b = _calls(transcript(messages))
    assert (a["result"], a["status"]) == ("for a", "error")
    assert (b["result"], b["status"]) == ("for b", "success")


def test_a_stray_result_is_ignored():
    messages = [
        HumanMessage("hi"),
        ToolMessage("orphan", tool_call_id="nobody"),
        AIMessage("", tool_calls=[_call("q", "nobody")]),
    ]
    (call,) = _calls(transcript(messages))
    assert call["status"] == "pending"
