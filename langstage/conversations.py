"""Past chat conversations, read from the server's checkpointer (gh #232).

Every chat turn is checkpointed under its session id (the LangGraph ``thread_id``), so
the conversations already exist; the UI could only reach the one whose id sat in the
browser's ``localStorage``. This module lists them, renders one as a transcript, and
deletes one, using only the checkpointer API (``alist`` / ``aget_state`` /
``adelete_thread``), never the saver's own tables, so a user-supplied saver works too.

Listing cost
------------
No checkpointer API lists threads. ``alist(None)`` walks every checkpoint of every
thread, newest first, and deserializes each one: about 1.3 ms per checkpoint on the
SQLite saver, which is 16 s for a 150 MB database (300 threads, 12,000 checkpoints).
That can't run per request, so the list is served from an in-memory index:

- one background scan per server start fills it, newest threads first. The SQLite
  saver holds its lock for a whole ``alist`` call, which would stall every running
  turn for the length of the scan, so for the saver LangStage attaches the scan
  reads through a second saver on the same file (``scan_reader``): its own
  connection and lock, and SQLite's WAL mode lets it read while turns write.
  (Paging one saver with ``before=``/``limit=`` is not an option: SQLite has no
  index on ``checkpoint_id`` alone, so every page re-sorts the table, and the same
  database took 129 s.) A saver the user supplied is read in one ``alist`` pass;
- after that, a turn marks its own thread stale and the next list request re-reads
  just that thread (one ``aget_state``, about 4 ms). A list request itself is a
  dictionary sort: under 1 ms for 240 conversations.

Nothing is persisted, so the index can't disagree with the checkpointer after a
restart: it is rebuilt from it.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Thread-id prefixes that are not chats: the task board's runs (``TaskRunner``'s
#: ``task-<id>`` threads, which is also what a schedule enqueues) and a schedule's
#: own session name. The Board already shows those.
TASK_THREAD_PREFIXES = ("task-", "cron-")

#: Longest title the list returns (the first user message, shortened).
TITLE_MAX = 80

#: How long a list request waits for the first scan before answering with what is
#: indexed so far (``indexing: true``). A normal database finishes well inside it.
SCAN_WAIT_S = 1.5

#: Default and largest page of the list.
LIST_LIMIT = 50
LIST_LIMIT_MAX = 200

# Printable, no path separators: a session id is a UUID by default, but a client may
# name its own, so this only refuses what can't be a real id.
_THREAD_ID = re.compile(r"^[^\x00-\x1f\x7f/\\]{1,200}$")

# The lines routes_chat.context_parts() puts before what the user typed.
_CONTEXT_LINE = re.compile(r"^\[(?:Current time|Working directory|File browser folder): [^\n]*\]$")


class ConversationBusy(Exception):
    """The thread has a running turn or another window attached to it."""

    def __init__(self, detail: str, *, running: bool, connected: bool) -> None:
        super().__init__(detail)
        self.detail = detail
        self.running = running
        self.connected = connected


class HistoryUnsupported(Exception):
    """The checkpointer can't do what was asked (list or delete threads)."""


def is_chat_thread(thread_id: str) -> bool:
    """False for the task board's and the scheduler's threads."""
    return not thread_id.startswith(TASK_THREAD_PREFIXES)


def valid_thread_id(thread_id: str) -> bool:
    return bool(_THREAD_ID.match(thread_id)) and thread_id.strip() == thread_id


def typed_text(content: str) -> str:
    """What the user typed, without the context lines the server put before it."""
    head, sep, rest = content.partition("\n\n")
    if sep and head and all(_CONTEXT_LINE.match(line) for line in head.split("\n")):
        return rest
    return content


def _field(message: Any, name: str) -> Any:
    return message.get(name) if isinstance(message, dict) else getattr(message, name, None)


def _kind(message: Any) -> str:
    kind = _field(message, "type") or _field(message, "role") or ""
    return {"AIMessageChunk": "ai", "assistant": "ai", "user": "human"}.get(kind, kind)


def _text(message: Any) -> str:
    """All of a message's text blocks joined (reasoning blocks are not text)."""
    try:
        from langstage_core.agui import _message_text

        if not isinstance(message, dict):
            return _message_text(message)
    except ImportError:  # pragma: no cover - an older core
        pass
    content = _field(message, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else (block.get("text") or "")
            for block in content
            if isinstance(block, str) or (isinstance(block, dict) and block.get("type") == "text")
        )
    return ""


def _reasoning(message: Any) -> str:
    try:
        from langstage_core.agui import _message_reasoning
    except ImportError:  # pragma: no cover - an older core
        return ""
    try:
        return "\n\n".join(text for _id, text in _message_reasoning(message))
    except Exception:  # noqa: BLE001 - reasoning is optional detail
        return ""


def title_of(text: str) -> str:
    """A one-line title from the first user message."""
    line = " ".join(typed_text(text).split())
    if not line:
        return "(no text)"
    return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 1].rstrip() + "…"


def summarize(messages: Any) -> dict[str, Any] | None:
    """``{title, message_count}`` for a thread's messages, or None when it holds no
    user message (not a conversation: nothing to show or reopen)."""
    if not isinstance(messages, (list, tuple)):
        return None
    first: str | None = None
    count = 0
    for message in messages:
        kind = _kind(message)
        if kind == "human":
            count += 1
            if first is None:
                first = _text(message)
        elif kind == "ai" and _text(message):
            count += 1
    if first is None:
        return None
    return {"title": title_of(first), "message_count": count}


def transcript(messages: Any, *, max_result_len: int = 50_000) -> list[dict[str, Any]]:
    """A thread's messages as the chat shows them.

    One entry per user message and per assistant message. An assistant entry carries
    its text, its reasoning when the state kept it, and its tool calls, each with the
    result of the ``ToolMessage`` that answered it (``status`` is ``pending`` when
    none did: the call is awaiting an approval, or its turn was stopped). System
    messages and the context lines before a user message are left out.
    """
    if not isinstance(messages, (list, tuple)):
        return []
    results = {
        _field(m, "tool_call_id"): m for m in messages if _kind(m) == "tool"
    }
    out: list[dict[str, Any]] = []
    for message in messages:
        kind = _kind(message)
        if kind == "human":
            out.append({"role": "user", "content": typed_text(_text(message))})
        elif kind == "ai":
            text = _text(message)
            reasoning = _reasoning(message)
            calls = []
            for index, call in enumerate(_field(message, "tool_calls") or []):
                if not isinstance(call, dict):
                    continue
                call_id = call.get("id") or f"{_field(message, 'id')}-call-{index}"
                args = call.get("args")
                entry: dict[str, Any] = {
                    "id": str(call_id),
                    "name": call.get("name") or "tool",
                    "args": args if isinstance(args, dict) else {"_raw": args},
                    "status": "pending",
                }
                result = results.get(call.get("id"))
                if result is not None:
                    body = _field(result, "content")
                    body = body if isinstance(body, str) else (_text(result) or str(body))
                    if len(body) > max_result_len:
                        body = body[:max_result_len] + "…(truncated)"
                    entry["status"] = "error" if _field(result, "status") == "error" else "success"
                    entry["result"] = body
                calls.append(entry)
            if not (text or reasoning or calls):
                continue
            entry = {"role": "assistant", "content": text, "tool_calls": calls}
            if reasoning:
                entry["reasoning"] = reasoning
            out.append(entry)
    return out


def _overrides(saver: Any, method: str) -> bool:
    """Does the saver's class implement ``method`` itself (the base one raises)?"""
    try:
        from langgraph.checkpoint.base import BaseCheckpointSaver
    except ImportError:  # pragma: no cover - langgraph is a hard dependency
        return callable(getattr(saver, method, None))
    own = getattr(type(saver), method, None)
    return own is not None and own is not getattr(BaseCheckpointSaver, method, None)


def history_support(saver: Any) -> tuple[bool, bool, str]:
    """``(can_list, can_delete, detail)`` for a checkpointer, without calling it."""
    kind = type(saver).__name__
    if saver is None or isinstance(saver, bool):
        return False, False, "no checkpointer"
    can_list = _overrides(saver, "alist")
    can_delete = _overrides(saver, "adelete_thread")
    if not can_list:
        return False, can_delete, f"{kind} can't list threads (no alist)"
    if not can_delete:
        return True, False, f"{kind} can list threads but not delete them (no adelete_thread)"
    return True, True, f"{kind} lists and deletes threads"


class Conversations:
    """The index of chat threads behind ``/api/conversations``."""

    def __init__(
        self, agent: Any, adapter: Any, *, max_result_len: int = 50_000, consumers: Any = None
    ) -> None:
        self._agent = agent
        self._adapter = adapter
        #: The server's ``StreamConsumers``: who is reading each session's stream.
        self._consumers = consumers
        self._max_result_len = max_result_len
        self._rows: dict[str, dict[str, Any]] = {}
        self._stale: set[str] = set()
        self._scan_task: asyncio.Task | None = None
        self._scan_done: asyncio.Event | None = None
        self._scanned_saver: Any = None
        self._unlistable: str | None = None
        #: Optional ``() -> async context manager`` yielding a second saver on the
        #: same store, used only to read it during the scan (see the module docstring).
        self.scan_reader: Callable[[], Any] | None = None

    # ── the checkpointer ─────────────────────────────────────────────

    @property
    def saver(self) -> Any:
        # Read on every use: the server swaps its in-memory saver for SQLite at startup.
        saver = getattr(self._agent, "checkpointer", None)
        return None if isinstance(saver, bool) else saver

    def support(self) -> tuple[bool, bool, str]:
        can_list, can_delete, detail = history_support(self.saver)
        if can_list and self._unlistable:
            return False, can_delete, self._unlistable
        if can_list and not callable(getattr(self._agent, "aget_state", None)):
            return False, can_delete, "the agent can't read thread state (no aget_state)"
        return can_list, can_delete, detail

    def durable(self) -> bool:
        return "memory" not in type(self.saver).__name__.lower()

    # ── keeping the index fresh ──────────────────────────────────────

    def touch(self, thread_id: str) -> None:
        """A turn started or ended on this thread: re-read it before the next list."""
        if isinstance(thread_id, str) and is_chat_thread(thread_id):
            self._stale.add(thread_id)

    def start(self) -> None:
        """Start the background scan, once per checkpointer (needs a running loop)."""
        saver = self.saver
        if saver is None or (self._scan_task is not None and self._scanned_saver is saver):
            return
        if self._scan_task is not None:
            self._scan_task.cancel()  # the saver was swapped: what was read is void
            self._rows.clear()
        self._scanned_saver = saver
        self._unlistable = None
        self._scan_done = asyncio.Event()
        self._scan_task = asyncio.get_running_loop().create_task(self._scan(saver, self._scan_done))

    async def stop(self) -> None:
        task, self._scan_task = self._scan_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - cancelled, or already failed and logged
                pass

    async def _scan(self, saver: Any, done: asyncio.Event) -> None:
        seen: set[str] = set()
        try:
            if not _overrides(saver, "alist"):
                return
            if self.scan_reader is not None:
                async with self.scan_reader() as reader:
                    async for tup in reader.alist(None):
                        self._index(tup, seen)
            else:
                async for tup in saver.alist(None):
                    self._index(tup, seen)
        except asyncio.CancelledError:
            raise
        except NotImplementedError as exc:
            # e.g. the synchronous SqliteSaver: it defines alist, which then refuses.
            self._unlistable = f"{type(saver).__name__} can't list threads ({exc or 'alist is not implemented'})"
        except Exception:  # noqa: BLE001 - history is best-effort; keep what was read
            logger.warning("Listing past conversations stopped early.", exc_info=True)
        finally:
            done.set()

    def _index(self, tup: Any, seen: set[str]) -> None:
        conf = (getattr(tup, "config", None) or {}).get("configurable", {})
        thread_id = conf.get("thread_id")
        if conf.get("checkpoint_ns") or not isinstance(thread_id, str):
            return  # a subgraph's checkpoint: the parent's carries the conversation
        if thread_id in seen:
            return  # an older checkpoint of a thread already read
        seen.add(thread_id)
        if not is_chat_thread(thread_id) or thread_id in self._rows or thread_id in self._stale:
            return
        checkpoint = getattr(tup, "checkpoint", None) or {}
        messages = (checkpoint.get("channel_values") or {}).get("messages")
        if not isinstance(messages, (list, tuple)):
            self._stale.add(thread_id)  # not stored inline: read it through the graph
            return
        row = summarize(messages)
        if row is None:
            return
        paused = any(
            len(write) > 1 and write[1] == "__interrupt__"
            for write in getattr(tup, "pending_writes", None) or ()
        )
        self._rows[thread_id] = {
            "thread_id": thread_id,
            **row,
            "updated_at": checkpoint.get("ts"),
            "paused": paused,
        }

    async def _state(self, thread_id: str) -> Any:
        aget_state = getattr(self._agent, "aget_state", None)
        if aget_state is None:
            raise HistoryUnsupported("the agent can't read thread state (no aget_state)")
        return await aget_state({"configurable": {"thread_id": thread_id}})

    @staticmethod
    def _row_from_state(thread_id: str, state: Any) -> dict[str, Any] | None:
        if getattr(state, "created_at", None) is None:
            return None  # no checkpoint: the thread doesn't exist
        values = getattr(state, "values", None)
        row = summarize(values.get("messages") if isinstance(values, dict) else None)
        if row is None:
            return None
        paused = any(getattr(task, "interrupts", None) for task in getattr(state, "tasks", None) or ())
        return {"thread_id": thread_id, **row, "updated_at": state.created_at, "paused": paused}

    async def _refresh(self, thread_id: str) -> dict[str, Any] | None:
        try:
            row = self._row_from_state(thread_id, await self._state(thread_id))
        except HistoryUnsupported:
            raise
        except Exception:  # noqa: BLE001 - e.g. a checkpoint the current agent can't read
            logger.debug("Could not read thread %s", thread_id, exc_info=True)
            return self._rows.get(thread_id)
        if row is None:
            self._rows.pop(thread_id, None)
        else:
            self._rows[thread_id] = row
        return row

    def _live(self, thread_id: str) -> tuple[bool, bool]:
        """``(running, connected)``: a turn in flight, a browser attached."""
        session = self._adapter.get(thread_id)
        if session is None:
            return False, False
        task = session.current_task
        connected = bool(session.sse_connected)
        if self._consumers is not None:
            connected = connected or self._consumers.attached(thread_id)
        return task is not None and not task.done(), connected

    # ── the API ──────────────────────────────────────────────────────

    async def list(self, *, limit: int = LIST_LIMIT, offset: int = 0) -> dict[str, Any]:
        can_list, can_delete, detail = self.support()
        if not can_list:
            return {"available": False, "reason": detail, "can_delete": False,
                    "durable": False, "indexing": False, "total": 0, "conversations": []}
        self.start()
        done = self._scan_done
        if done is not None and not done.is_set():
            try:
                async with asyncio.timeout(SCAN_WAIT_S):
                    await done.wait()
            except TimeoutError:
                pass
        can_list, can_delete, detail = self.support()  # the scan may have been refused
        if not can_list:
            return {"available": False, "reason": detail, "can_delete": False,
                    "durable": False, "indexing": False, "total": 0, "conversations": []}
        for thread_id in sorted(self._stale):
            await self._refresh(thread_id)
            if not self._live(thread_id)[0]:
                self._stale.discard(thread_id)  # a running turn stays stale until it ends
        rows = sorted(self._rows.values(), key=lambda r: r.get("updated_at") or "", reverse=True)
        page = []
        for row in rows[offset: offset + limit]:
            running, connected = self._live(row["thread_id"])
            page.append({**row, "running": running, "connected": connected})
        return {
            "available": True,
            "can_delete": can_delete,
            "durable": self.durable(),
            "indexing": bool(done is not None and not done.is_set()),
            "total": len(rows),
            "conversations": page,
        }

    async def get(self, thread_id: str) -> dict[str, Any] | None:
        """One conversation with its transcript, or None when there is no such chat."""
        if not valid_thread_id(thread_id) or not is_chat_thread(thread_id):
            return None
        if self.saver is None:
            return None
        state = await self._state(thread_id)
        row = self._row_from_state(thread_id, state)
        if row is None:
            self._rows.pop(thread_id, None)
            return None
        self._rows[thread_id] = row
        running, connected = self._live(thread_id)
        return {
            **row,
            "running": running,
            "connected": connected,
            "interrupt": None if running else _pending_interrupt(state),
            "messages": transcript(state.values.get("messages"), max_result_len=self._max_result_len),
        }

    async def open(self, thread_id: str, *, takeover: bool = False) -> dict[str, Any] | None:
        """Take the conversation over for a browser that is about to attach to it.

        Refused while a turn is running or another window is attached: one session
        feeds one event stream, so a second consumer would split the frames between
        the two windows. Frames left queued by a turn nobody watched to the end are
        dropped, because the transcript returned here already holds what they said.

        With ``takeover``, a window that is attached is made to let go first (its
        stream ends with a ``superseded`` frame), so the caller can attach. A running
        turn is still a refusal: its frames can't be moved to another window whole.
        """
        detail = await self.get(thread_id)
        if detail is None:
            return None
        if detail["running"] or (detail["connected"] and not takeover):
            raise ConversationBusy(
                "a turn is running in this conversation" if detail["running"]
                else "this conversation is open in another window",
                running=detail["running"], connected=detail["connected"],
            )
        if detail["connected"]:
            released = self._consumers is not None and await self._consumers.take_over(thread_id)
            running = self._live(thread_id)[0]
            if not released or running:
                # No registry to ask, the reader would not stop, or a turn started
                # while it was stopping.
                raise ConversationBusy(
                    "a turn is running in this conversation" if running
                    else "this conversation is open in another window",
                    running=running, connected=True,
                )
            detail = await self.get(thread_id)
            if detail is None:
                return None
            detail["connected"] = False  # the window that had it has just let go
        session = self._adapter.get(thread_id)
        if session is not None:
            while not session.event_queue.empty():
                session.event_queue.get_nowait()
        if self._consumers is not None:
            self._consumers.forget(thread_id)  # frames a reader took but never wrote
        return detail

    async def delete(self, thread_id: str) -> bool:
        """Remove the thread from the checkpointer. False when there is no such chat."""
        if not valid_thread_id(thread_id) or not is_chat_thread(thread_id):
            return False
        saver = self.saver
        if saver is None or not _overrides(saver, "adelete_thread"):
            raise HistoryUnsupported(f"{type(saver).__name__} can't delete threads (no adelete_thread)")
        if self._live(thread_id)[0]:
            raise ConversationBusy(
                "a turn is running in this conversation; stop it before deleting",
                running=True, connected=self._live(thread_id)[1],
            )
        if self._row_from_state(thread_id, await self._state(thread_id)) is None:
            self._rows.pop(thread_id, None)
            return False
        try:
            await saver.adelete_thread(thread_id)
        except NotImplementedError as exc:
            raise HistoryUnsupported(f"{type(saver).__name__} can't delete threads") from exc
        self._adapter.delete_session(thread_id)
        if self._consumers is not None:
            self._consumers.forget(thread_id)
        self._rows.pop(thread_id, None)
        self._stale.discard(thread_id)
        return True


def _pending_interrupt(state: Any) -> dict[str, Any] | None:
    """The approval a paused thread is waiting on, as the ``interrupt`` frame the chat
    stream would have sent, so a reopened conversation can still be answered."""
    pending = [
        interrupt
        for task in getattr(state, "tasks", None) or ()
        for interrupt in getattr(task, "interrupts", None) or ()
    ]
    if not pending:
        return None
    try:
        from langstage_core.agui import _normalize_interrupt

        requests, review_configs, decisions = _normalize_interrupt(getattr(pending[-1], "value", None))
    except Exception:  # noqa: BLE001 - an older core, or a value it can't read
        return {"type": "interrupt", "action_requests": [], "review_configs": [],
                "allowed_decisions": ["approve", "reject"]}
    import json

    def safe(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return json.loads(json.dumps(value, default=str))

    return {"type": "interrupt", "action_requests": safe(requests),
            "review_configs": safe(review_configs), "allowed_decisions": list(decisions)}
