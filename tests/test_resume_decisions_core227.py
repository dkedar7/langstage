"""A refused HITL decision is answered 400 and the approval stays answerable (core #227).

``/api/chat/interrupt`` and ``/api/tasks/{id}/resume`` check the decisions against the
pending approval with ``langstage_core.decision_problems`` before resuming. An answer
``HumanInTheLoopMiddleware`` would refuse (a type the tool doesn't allow) is never sent:
the chat session keeps its interrupt and the task stays in review, so a correct answer
still goes through.
"""
import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langchain.agents.middleware")

from langchain.agents import create_agent  # noqa: E402
from langchain.agents.middleware import HumanInTheLoopMiddleware  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from langstage_core.adapters import SessionAdapter  # noqa: E402
from langstage_core.tasks import TaskRunner  # noqa: E402
from langstage_core.tasks.state import DONE, REVIEW_NEEDED  # noqa: E402
from langstage.server.routes_chat import create_chat_router  # noqa: E402
from langstage.server.routes_tasks import create_tasks_router  # noqa: E402
from langstage.tasks import SqliteTaskStore  # noqa: E402


@tool
def send_email(to: str) -> str:
    """Send an email."""
    return f"sent to {to}"


class _Model(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        if any(isinstance(m, ToolMessage) for m in messages):
            msg = AIMessage(content="Done.")
        else:
            msg = AIMessage(content="", tool_calls=[
                {"name": "send_email", "args": {"to": "a@example.org"}, "id": "c1"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _graph():
    return create_agent(_Model(), tools=[send_email], middleware=[
        HumanInTheLoopMiddleware(interrupt_on={"send_email": {"allowed_decisions": ["approve", "edit"]}}),
    ])


async def _wait(cond, timeout=6.0):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        value = await cond()
        if value:
            return value
        await asyncio.sleep(0.02)
    raise AssertionError("condition never held")


async def test_task_resume_refuses_a_disallowed_decision_then_accepts(tmp_path):
    store = SqliteTaskStore(tmp_path / "tasks.db")
    await store.setup()
    runner = TaskRunner(SessionAdapter(graph=_graph()), store, concurrency=1, poll_interval=0.05)
    await runner.start()
    app = FastAPI()
    app.include_router(create_tasks_router(runner, store))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            tid = (await client.post("/api/tasks", json={"prompt": "email a"})).json()["task_id"]

            async def in_review():
                row = await store.get(tid)
                return row if row and row["state"] == REVIEW_NEEDED else None

            await _wait(in_review)
            bad = await client.post(f"/api/tasks/{tid}/resume", json={"decisions": [{"type": "reject"}]})
            assert bad.status_code == 400
            assert "'reject' is not allowed; allowed: approve, edit" in bad.json()["detail"]
            assert (await store.get(tid))["state"] == REVIEW_NEEDED  # still answerable

            ok = await client.post(f"/api/tasks/{tid}/resume", json={"decisions": [{"type": "approve"}]})
            assert ok.status_code == 200

            async def done():
                row = await store.get(tid)
                return row if row and row["state"] == DONE else None

            row = await _wait(done)
            assert "Done." in (row["result"] or "")
    finally:
        await runner.shutdown()
        await store.close()


async def test_chat_interrupt_refuses_a_disallowed_decision_then_accepts():
    adapter = SessionAdapter(graph=_graph())
    app = FastAPI()
    app.include_router(create_chat_router(adapter))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        session = adapter.submit_message(None, "email a")  # what /api/chat + /api/stream start
        sid = session.id

        async def interrupted():
            return session.interrupt if session.interrupt and session.outcome else None

        await _wait(interrupted)
        bad = await client.post("/api/chat/interrupt", json={"session_id": sid, "decisions": [{"type": "reject"}]})
        assert bad.status_code == 400
        assert "allowed: approve, edit" in bad.json()["detail"]
        assert session.interrupt  # nothing was sent; the approval is still pending

        ok = await client.post("/api/chat/interrupt", json={"session_id": sid, "decisions": [{"type": "approve"}]})
        assert ok.status_code == 200

        async def finished():
            return session.outcome == "complete" or None

        await _wait(finished)
