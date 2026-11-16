"""Past conversations can be listed, reopened, continued and deleted (gh #232).

Chats were always checkpointed under their session id, but the UI could reach only
the one whose id sat in the browser's localStorage. ``/api/conversations`` reads the
rest back from the checkpointer.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from click.testing import CliRunner
from httpx import ASGITransport, AsyncClient

pytest.importorskip("ag_ui_langgraph")
pytest.importorskip("langchain.agents.middleware")

from langchain.agents import create_agent  # noqa: E402
from langchain.agents.middleware import HumanInTheLoopMiddleware  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.checkpoint.base import BaseCheckpointSaver  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from langstage import CoworkApp  # noqa: E402
from langstage import cli as cli_mod  # noqa: E402
from langstage import conversations as conv  # noqa: E402
from langstage.server.routes_chat import context_parts  # noqa: E402


@tool
def lookup(q: str) -> str:
    """Look something up."""
    return f"ANSWER for {q}"


@tool
def send_email(to: str) -> str:
    """Send an email."""
    return f"sent to {to}"


class _Model(BaseChatModel):
    """Calls ``lookup`` once per user message, then answers with the turn number."""

    tool_name: str = "lookup"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        turns = sum(isinstance(m, HumanMessage) for m in messages)
        if isinstance(messages[-1], ToolMessage):
            msg = AIMessage(content=f"Reply {turns}: {messages[-1].content}")
        else:
            args = {"to": "a@example.org"} if self.tool_name == "send_email" else {"q": f"q{turns}"}
            msg = AIMessage(content="", tool_calls=[
                {"name": self.tool_name, "args": args, "id": f"call-{turns}"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _agent(**kwargs):
    return create_agent(_Model(), tools=[lookup], **kwargs)


def _hitl_agent(**kwargs):
    return create_agent(_Model(tool_name="send_email"), tools=[send_email], middleware=[
        HumanInTheLoopMiddleware(interrupt_on={"send_email": {"allowed_decisions": ["approve", "reject"]}}),
    ], **kwargs)


class _Served:
    """A running app (lifespan entered) plus an HTTP client on it."""

    def __init__(self, agent, workspace, **app_kwargs):
        self.app = CoworkApp(agent=agent, workspace=str(workspace), **app_kwargs).create_server()
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://localhost")

    async def __aenter__(self):
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()
        await self._lifespan.__aexit__(None, None, None)

    @property
    def adapter(self):
        return self.app.state.session_adapter

    async def turn(self, text: str, session_id: str | None = None) -> str:
        body = {"content": text}
        if session_id:
            body["session_id"] = session_id
        resp = await self.client.post("/api/chat/complete", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()["session_id"]

    async def listing(self, **params) -> dict:
        resp = await self.client.get("/api/conversations", params=params)
        assert resp.status_code == 200, resp.text
        return resp.json()


async def _wait(cond, timeout=8.0):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        value = await cond()
        if value:
            return value
        await asyncio.sleep(0.02)
    raise AssertionError("condition never held")


# ── the pure parts ───────────────────────────────────────────────────────────


def test_typed_text_drops_only_the_servers_context_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGSTAGE_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "reports").mkdir()
    prefix = "\n".join(context_parts("/reports")) + "\n\n"
    assert prefix.count("\n") >= 3  # time, working directory, file browser folder
    assert conv.typed_text(prefix + "what is 2+2?\n\nshow your work") == "what is 2+2?\n\nshow your work"
    # A message that merely starts with a bracketed line is the user's own text.
    own = "[draft] first line\n\nsecond paragraph"
    assert conv.typed_text(own) == own
    assert conv.typed_text("plain") == "plain"


def test_title_is_one_short_line():
    assert conv.title_of("[Current time: x]\n[Working directory: /w]\n\n  Summarize\nthe   Acme report ") == \
        "Summarize the Acme report"
    long = conv.title_of("word " * 100)
    assert len(long) == conv.TITLE_MAX and long.endswith("…")
    assert conv.title_of("   ") == "(no text)"


def test_transcript_pairs_tool_results_and_keeps_reasoning():
    messages = [
        SystemMessage("be brief"),
        HumanMessage("[Current time: x]\n[Working directory: /w]\n\nfind x"),
        AIMessage(content=[{"type": "thinking", "thinking": "I should look it up."},
                           {"type": "text", "text": "Looking."}],
                  tool_calls=[{"name": "lookup", "args": {"q": "x"}, "id": "c1"},
                              {"name": "lookup", "args": {"q": "y"}, "id": "c2"},
                              {"name": "lookup", "args": {"q": "z"}, "id": "c3"}]),
        ToolMessage("ANSWER for x", tool_call_id="c1"),
        ToolMessage("boom", tool_call_id="c2", status="error"),
        AIMessage("x is 42."),
        AIMessage(""),  # nothing to show
    ]
    out = conv.transcript(messages, max_result_len=8)
    assert [m["role"] for m in out] == ["user", "assistant", "assistant"]
    assert out[0] == {"role": "user", "content": "find x"}
    first = out[1]
    assert first["content"] == "Looking." and first["reasoning"] == "I should look it up."
    assert [(c["id"], c["status"]) for c in first["tool_calls"]] == [
        ("c1", "success"), ("c2", "error"), ("c3", "pending")]
    assert first["tool_calls"][0]["result"] == "ANSWER f…(truncated)"
    assert first["tool_calls"][0]["args"] == {"q": "x"}
    assert "result" not in first["tool_calls"][2]
    assert out[2] == {"role": "assistant", "content": "x is 42.", "tool_calls": []}
    assert conv.summarize(messages) == {"title": "find x", "message_count": 3}
    assert conv.summarize([AIMessage("no user turn")]) is None
    assert conv.summarize(None) is None


@pytest.mark.parametrize("thread_id,ok", [
    ("2b5cc72c-b2cc-4494-b865-76f3f4d40841", True),
    ("my session 1", True),
    ("", False), ("a/b", False), ("a\\b", False), ("x\ny", False), (" padded ", False),
    ("x" * 201, False),
])
def test_thread_id_validation(thread_id, ok):
    assert conv.valid_thread_id(thread_id) is ok


# ── list / read / continue / delete on a served app ──────────────────────────


async def test_conversation_is_listed_read_and_continued(tmp_path):
    async with _Served(_agent(), tmp_path) as s:
        empty = await s.listing()
        assert empty["available"] is True and empty["conversations"] == [] and empty["total"] == 0
        assert empty["durable"] is True and empty["can_delete"] is True  # the SQLite saver

        first = await s.turn("use a tool MANGO")
        await asyncio.sleep(0.01)
        second = await s.turn("something unrelated")
        listed = await s.listing()
        assert [c["thread_id"] for c in listed["conversations"]] == [second, first]  # newest first
        row = listed["conversations"][1]
        assert row["title"] == "use a tool MANGO" and row["message_count"] == 2
        assert row["running"] is False and row["connected"] is False and row["paused"] is False
        assert row["updated_at"]

        detail = (await s.client.get(f"/api/conversations/{first}")).json()
        assert detail["thread_id"] == first and detail["interrupt"] is None
        roles = [m["role"] for m in detail["messages"]]
        assert roles == ["user", "assistant", "assistant"]
        assert detail["messages"][0]["content"] == "use a tool MANGO"  # no context lines
        call = detail["messages"][1]["tool_calls"][0]
        assert (call["name"], call["args"], call["status"], call["result"]) == (
            "lookup", {"q": "q1"}, "success", "ANSWER for q1")
        assert detail["messages"][2]["content"] == "Reply 1: ANSWER for q1"

        # Continuing it runs on the same thread, with the earlier turn still in state.
        assert await s.turn("and again", session_id=first) == first
        again = (await s.client.get(f"/api/conversations/{first}")).json()
        assert again["messages"][-1]["content"] == "Reply 2: ANSWER for q2"
        assert again["message_count"] == 4
        relisted = await s.listing()
        assert [c["thread_id"] for c in relisted["conversations"]] == [first, second]
        assert relisted["conversations"][0]["updated_at"] > row["updated_at"]


async def test_conversations_survive_a_restart_and_a_cleared_session(tmp_path):
    """The issue's evidence: New drops the session, a restart drops the process; the
    thread is still in checkpoints.db and is listed and continued."""
    async with _Served(_agent(), tmp_path) as s:
        sid = await s.turn("use a tool MANGO")
        assert (await s.client.delete(f"/api/session/{sid}")).status_code == 200  # what New does
        assert [c["thread_id"] for c in (await s.listing())["conversations"]] == [sid]

    async with _Served(_agent(), tmp_path) as s:
        listed = await s.listing()
        assert [(c["thread_id"], c["title"]) for c in listed["conversations"]] == [(sid, "use a tool MANGO")]
        opened = await s.client.post(f"/api/conversations/{sid}/open")
        assert opened.status_code == 200 and len(opened.json()["messages"]) == 3
        await s.turn("still there?", session_id=sid)
        detail = (await s.client.get(f"/api/conversations/{sid}")).json()
        assert detail["messages"][-1]["content"] == "Reply 2: ANSWER for q2"


async def test_task_and_schedule_threads_are_not_conversations(tmp_path):
    async with _Served(_agent(), tmp_path) as s:
        sid = await s.turn("a chat")
        task = (await s.client.post("/api/tasks", json={"prompt": "a task"})).json()

        async def done():
            row = (await s.client.get(f"/api/tasks/{task['task_id']}")).json()
            return row if row["state"] == "done" else None

        thread = (await _wait(done))["thread_id"]
        assert thread.startswith("task-")
        assert [c["thread_id"] for c in (await s.listing())["conversations"]] == [sid]
        for request in (s.client.get, s.client.delete):
            assert (await request(f"/api/conversations/{thread}")).status_code == 404
        assert (await s.client.post(f"/api/conversations/{thread}/open")).status_code == 404
        assert (await s.client.get("/api/conversations/cron-ab12cd34")).status_code == 404
        # ... and the task's thread is untouched.
        state = await s.app.state.session_adapter._graph.aget_state({"configurable": {"thread_id": thread}})
        assert state.values["messages"]

    # A restart scans the database: the task's thread is still left out.
    async with _Served(_agent(), tmp_path) as s:
        assert [c["thread_id"] for c in (await s.listing())["conversations"]] == [sid]


async def test_delete_removes_the_thread_for_good(tmp_path):
    async with _Served(_agent(), tmp_path) as s:
        keep = await s.turn("keep me")
        drop = await s.turn("drop me")
        assert (await s.client.delete(f"/api/conversations/{drop}")).json() == {"ok": True}
        assert [c["thread_id"] for c in (await s.listing())["conversations"]] == [keep]
        assert (await s.client.get(f"/api/conversations/{drop}")).status_code == 404
        assert (await s.client.delete(f"/api/conversations/{drop}")).status_code == 404
        assert s.adapter.get(drop) is None
        saver = s.adapter._graph.checkpointer
        assert await saver.aget_tuple({"configurable": {"thread_id": drop}}) is None

    async with _Served(_agent(), tmp_path) as s:  # gone from the database too
        assert [c["thread_id"] for c in (await s.listing())["conversations"]] == [keep]


async def test_ids_are_validated_and_unknown_ones_are_404(tmp_path):
    async with _Served(_agent(), tmp_path) as s:
        await s.turn("hello")
        for bad in ("x" * 201, "a%0Ab", "back%5Cslash"):
            for request in (s.client.get, s.client.delete):
                assert (await request(f"/api/conversations/{bad}")).status_code == 400, bad
            assert (await s.client.post(f"/api/conversations/{bad}/open")).status_code == 400
        for request in (s.client.get, s.client.delete):
            resp = await request("/api/conversations/no-such-thread")
            assert resp.status_code == 404 and resp.json()["detail"] == "Conversation not found"
        assert (await s.client.post("/api/conversations/no-such-thread/open")).status_code == 404
        # Asking about an unknown thread must not create it.
        assert (await s.listing())["total"] == 1
        assert (await s.client.get("/api/conversations", params={"limit": 0})).status_code == 422
        assert (await s.client.get("/api/conversations", params={"limit": 201})).status_code == 422


async def test_list_is_paged(tmp_path):
    async with _Served(_agent(), tmp_path) as s:
        ids = []
        for n in range(5):
            ids.append(await s.turn(f"conversation {n}"))
            await asyncio.sleep(0.005)
        page = await s.listing(limit=2, offset=1)
        assert page["total"] == 5
        assert [c["thread_id"] for c in page["conversations"]] == [ids[3], ids[2]]
        assert (await s.listing(offset=5))["conversations"] == []


# ── a thread that is live, or paused on an approval ──────────────────────────


async def test_a_running_or_attached_conversation_is_not_taken_over_or_deleted(tmp_path):
    async with _Served(_agent(), tmp_path) as s:
        sid = await s.turn("hello")
        session = s.adapter.get_or_create(sid)

        # Another window is attached: reading works, taking over is refused.
        session.sse_connected = True
        read = await s.client.get(f"/api/conversations/{sid}")
        assert read.status_code == 200 and read.json()["connected"] is True
        busy = await s.client.post(f"/api/conversations/{sid}/open")
        assert busy.status_code == 409
        assert busy.json()["detail"] == {
            "message": "this conversation is open in another window", "running": False, "connected": True}
        session.sse_connected = False

        # A turn is running: neither taken over nor deleted, and the list says so.
        release = asyncio.Event()
        session.current_task = asyncio.create_task(release.wait())
        row = (await s.listing())["conversations"][0]
        assert row["running"] is True
        busy = await s.client.post(f"/api/conversations/{sid}/open")
        assert busy.status_code == 409 and busy.json()["detail"]["running"] is True
        refused = await s.client.delete(f"/api/conversations/{sid}")
        assert refused.status_code == 409 and "stop it before deleting" in refused.json()["detail"]["message"]
        assert (await s.client.get(f"/api/conversations/{sid}")).status_code == 200  # still there
        release.set()
        await session.current_task

        # Free again. Frames a turn left queued (nobody watched it end) are dropped on
        # open: the transcript already holds what they said.
        session.push({"type": "content", "content": "stale"})
        opened = await s.client.post(f"/api/conversations/{sid}/open")
        assert opened.status_code == 200 and session.event_queue.empty()
        assert (await s.client.delete(f"/api/conversations/{sid}")).status_code == 200


async def test_a_conversation_paused_on_an_approval_can_be_reopened_and_answered(tmp_path):
    async with _Served(_hitl_agent(), tmp_path) as s:
        sid = (await s.client.post("/api/chat/complete", json={"content": "email a"})).json()["session_id"]
        row = (await s.listing())["conversations"][0]
        assert row["thread_id"] == sid and row["paused"] is True

    # After a restart the approval is only in the checkpoint. Reopening brings it back.
    async with _Served(_hitl_agent(), tmp_path) as s:
        assert (await s.listing())["conversations"][0]["paused"] is True
        detail = (await s.client.post(f"/api/conversations/{sid}/open")).json()
        interrupt = detail["interrupt"]
        assert interrupt["type"] == "interrupt"
        assert interrupt["action_requests"][0]["name"] == "send_email"
        assert sorted(interrupt["allowed_decisions"]) == ["approve", "reject"]
        pending = detail["messages"][-1]["tool_calls"][0]
        assert pending["status"] == "pending" and "result" not in pending

        session = s.adapter.get_or_create(sid)  # what attaching GET /api/stream does
        ok = await s.client.post("/api/chat/interrupt", json={"session_id": sid, "decisions": [{"type": "approve"}]})
        assert ok.status_code == 200

        async def finished():
            return session.outcome == "complete" or None

        await _wait(finished)
        detail = (await s.client.get(f"/api/conversations/{sid}")).json()
        assert detail["interrupt"] is None and detail["paused"] is False
        assert detail["messages"][-2]["tool_calls"][0]["result"] == "sent to a@example.org"
        assert detail["messages"][-1]["content"].startswith("Reply 1")

    # Deleting a paused conversation is how it is discarded.
    async with _Served(_hitl_agent(), tmp_path) as s:
        other = (await s.client.post("/api/chat/complete", json={"content": "email b"})).json()["session_id"]
        assert (await s.client.delete(f"/api/conversations/{other}")).status_code == 200


# ── auth ─────────────────────────────────────────────────────────────────────


async def test_auth_password_covers_the_conversation_routes(tmp_path):
    async with _Served(_agent(), tmp_path, auth_username="acme", auth_password="s3cret") as s:
        auth = ("acme", "s3cret")
        resp = await s.client.post("/api/chat/complete", json={"content": "private"}, auth=auth)
        sid = resp.json()["session_id"]
        for method, path in (
            ("GET", "/api/conversations"),
            ("GET", f"/api/conversations/{sid}"),
            ("POST", f"/api/conversations/{sid}/open"),
            ("DELETE", f"/api/conversations/{sid}"),
        ):
            assert (await s.client.request(method, path)).status_code == 401, (method, path)
            assert (await s.client.request(method, path, auth=("acme", "wrong"))).status_code == 401
        assert (await s.client.get(f"/api/conversations/{sid}", auth=auth)).status_code == 200  # not deleted
        assert (await s.client.delete(f"/api/conversations/{sid}", auth=auth)).status_code == 200


# ── other checkpointers ──────────────────────────────────────────────────────


class _NoListSaver(BaseCheckpointSaver):
    """A saver that stores state but implements neither ``alist`` nor ``adelete_thread``."""

    def __init__(self):
        super().__init__()
        self._inner = InMemorySaver()

    async def aget_tuple(self, config):
        return await self._inner.aget_tuple(config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self._inner.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        return await self._inner.aput_writes(config, writes, task_id, task_path)

    def get_next_version(self, current, channel):
        return self._inner.get_next_version(current, channel)


class _NoDeleteSaver(InMemorySaver):
    adelete_thread = BaseCheckpointSaver.adelete_thread
    delete_thread = BaseCheckpointSaver.delete_thread


async def test_a_checkpointer_that_cannot_list_threads_turns_history_off(tmp_path):
    async with _Served(_agent(checkpointer=_NoListSaver()), tmp_path) as s:
        sid = await s.turn("hello")
        listed = await s.listing()
        assert listed["available"] is False and listed["conversations"] == []
        assert "_NoListSaver can't list threads" in listed["reason"]
        # A thread whose id is known can still be read; it can't be deleted.
        assert (await s.client.get(f"/api/conversations/{sid}")).status_code == 200
        refused = await s.client.delete(f"/api/conversations/{sid}")
        assert refused.status_code == 501 and "can't delete threads" in refused.json()["detail"]


async def test_a_checkpointer_that_cannot_delete_threads_lists_but_refuses_delete(tmp_path):
    async with _Served(_agent(checkpointer=_NoDeleteSaver()), tmp_path) as s:
        sid = await s.turn("hello")
        listed = await s.listing()
        assert listed["available"] is True and listed["can_delete"] is False
        assert [c["thread_id"] for c in listed["conversations"]] == [sid]
        assert (await s.client.delete(f"/api/conversations/{sid}")).status_code == 501
        assert (await s.client.get(f"/api/conversations/{sid}")).status_code == 200


async def test_an_in_memory_checkpointer_lists_for_the_life_of_the_process(tmp_path):
    saver = InMemorySaver()
    async with _Served(_agent(checkpointer=saver), tmp_path) as s:
        first = await s.turn("one")
        second = await s.turn("two")
        listed = await s.listing()
        assert listed["available"] is True and listed["durable"] is False
        assert {c["thread_id"] for c in listed["conversations"]} == {first, second}
        assert (await s.client.delete(f"/api/conversations/{first}")).status_code == 200

    # The same saver object served again (a notebook restarting the server): the scan,
    # which reads an in-memory saver in one pass, finds what is still there.
    async with _Served(_agent(checkpointer=saver), tmp_path) as s:
        assert [c["thread_id"] for c in (await s.listing())["conversations"]] == [second]

    async with _Served(_agent(checkpointer=InMemorySaver()), tmp_path) as s:  # a new process
        assert (await s.listing())["conversations"] == []


# ── listing cost ─────────────────────────────────────────────────────────────


async def test_the_database_is_scanned_once_then_only_changed_threads_are_read(tmp_path, monkeypatch):
    async with _Served(_agent(), tmp_path) as s:
        ids = [await s.turn(f"conversation {n}") for n in range(4)]
        await s.turn("more", session_id=ids[0])

    async with _Served(_agent(), tmp_path) as s:
        index = s.app.state.conversations
        await index._scan_done.wait()  # the startup scan
        saver = s.adapter._graph.checkpointer
        scans: list[str] = []
        monkeypatch.setattr(saver, "alist", lambda *a, **k: scans.append("serving saver") or iter(()))
        real_reader = index.scan_reader

        def counting_reader():
            scans.append("reader")
            return real_reader()

        index.scan_reader = counting_reader
        index._rows.clear()
        index._scan_task = None  # scan again, counted
        listed = await s.listing()
        assert listed["indexing"] is False
        assert [c["thread_id"] for c in listed["conversations"]] == [ids[0], ids[3], ids[2], ids[1]]
        assert listed["conversations"][0]["message_count"] == 4
        # Read through the second connection: the saver turns write with is never
        # asked to list, so its lock isn't held for the scan.
        assert scans == ["reader"]

        states: list[str] = []
        real_state = s.adapter._graph.aget_state

        async def counting_state(config, **kwargs):
            states.append(config["configurable"]["thread_id"])
            return await real_state(config, **kwargs)

        monkeypatch.setattr(s.adapter._graph, "aget_state", counting_state)
        await s.listing()
        assert scans == ["reader"] and states == []  # served from the index

        await s.turn("a new turn", session_id=ids[2])
        states.clear()
        listed = await s.listing()
        assert listed["conversations"][0]["thread_id"] == ids[2]
        assert scans == ["reader"] and set(states) == {ids[2]}  # only the thread that changed


async def test_turns_run_while_the_database_is_being_scanned(tmp_path, monkeypatch):
    async with _Served(_agent(), tmp_path) as s:
        old = await s.turn("from the last run")

    monkeypatch.setattr(conv, "SCAN_WAIT_S", 0.05)
    async with _Served(_agent(), tmp_path) as s:
        index = s.app.state.conversations
        await index._scan_done.wait()
        gate = asyncio.Event()
        real_reader = index.scan_reader

        class _HeldOpen:
            """The reader, with its ``alist`` parked mid-scan until the gate opens."""

            async def __aenter__(self):
                self._cm = real_reader()
                self._saver = await self._cm.__aenter__()
                return self

            async def __aexit__(self, *exc):
                return await self._cm.__aexit__(*exc)

            async def alist(self, config, **kwargs):
                async for tup in self._saver.alist(config, **kwargs):
                    await gate.wait()
                    yield tup

        index.scan_reader = _HeldOpen
        index._rows.clear()
        index._scan_task = None
        assert (await s.listing())["indexing"] is True  # scan parked inside alist
        new = await asyncio.wait_for(s.turn("during the scan"), timeout=10)  # not blocked by it
        partial = await s.listing()
        assert partial["indexing"] is True
        assert [c["thread_id"] for c in partial["conversations"]] == [new]  # listed already
        gate.set()
        await index._scan_done.wait()
        assert [c["thread_id"] for c in (await s.listing())["conversations"]] == [new, old]


async def test_a_list_request_does_not_wait_for_a_long_scan(tmp_path, monkeypatch):
    async with _Served(_agent(), tmp_path) as s:
        sid = await s.turn("hello")

    monkeypatch.setattr(conv, "SCAN_WAIT_S", 0.05)
    async with _Served(_agent(), tmp_path) as s:
        gate = asyncio.Event()
        index = s.app.state.conversations
        real_scan = index._scan

        async def slow_scan(saver, done):
            await gate.wait()
            await real_scan(saver, done)

        await index.stop()
        monkeypatch.setattr(index, "_scan", slow_scan)
        partial = await s.listing()
        assert partial["indexing"] is True and partial["conversations"] == []
        gate.set()

        async def indexed():
            listed = await s.listing()
            return listed if not listed["indexing"] else None

        assert [c["thread_id"] for c in (await _wait(indexed))["conversations"]] == [sid]


# ── langstage check ──────────────────────────────────────────────────────────


def _graph_file(tmp_path, checkpointer_expr):
    agent = tmp_path / "hist_agent.py"
    agent.write_text(
        "from langgraph.graph import StateGraph, MessagesState, START, END\n"
        "from langgraph.checkpoint.base import BaseCheckpointSaver\n"
        "from langgraph.checkpoint.memory import InMemorySaver\n"
        "class NoList(BaseCheckpointSaver):\n"
        "    pass\n"
        "class NoDelete(InMemorySaver):\n"
        "    adelete_thread = BaseCheckpointSaver.adelete_thread\n"
        "g = StateGraph(MessagesState)\n"
        "g.add_node('n', lambda s: {'messages': []})\n"
        "g.add_edge(START, 'n'); g.add_edge('n', END)\n"
        f"graph = g.compile(checkpointer={checkpointer_expr})\n"
    )
    return f"{agent}:graph"


@pytest.mark.parametrize("expr,ok,needle", [
    ("None", True, "listed from the checkpointer"),
    ("InMemorySaver()", True, "listed from your checkpointer"),
    ("NoList()", False, "hidden: your checkpointer NoList can't list threads"),
    ("NoDelete()", True, "delete is off: your checkpointer NoDelete can list threads but not delete them"),
])
def test_check_says_whether_history_will_work(tmp_path, expr, ok, needle):
    import json

    spec = _graph_file(tmp_path, expr)
    human = CliRunner().invoke(cli_mod.main, ["check", "--agent", spec])
    line = next(ln for ln in human.output.splitlines() if "history:" in ln)
    assert needle in line and (("[warn]" in line) is (not ok)), line
    report = json.loads(CliRunner().invoke(cli_mod.main, ["check", "--agent", spec, "--json"]).output)
    assert report["checks"]["history"]["ok"] is ok and needle in report["checks"]["history"]["detail"]
    assert report["ok"] is True  # history is reported, never a failed check
