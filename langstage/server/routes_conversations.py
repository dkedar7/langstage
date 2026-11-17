"""REST endpoints for past chat conversations (gh #232).

``/api/conversations`` lists the chat threads the server's checkpointer holds, reads
one as a transcript, and deletes one. The task board's and the scheduler's threads
are not conversations and can't be reached here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from langstage.conversations import (
    LIST_LIMIT,
    LIST_LIMIT_MAX,
    ConversationBusy,
    Conversations,
    HistoryUnsupported,
    is_chat_thread,
    valid_thread_id,
)
from langstage.server.models import ConversationDetail, ConversationList, OkResponse
from langstage.tools import release_notebook_state

_NOT_FOUND = "Conversation not found"


def _check_id(thread_id: str) -> None:
    if not valid_thread_id(thread_id):
        raise HTTPException(status_code=400, detail="Invalid conversation id")
    if not is_chat_thread(thread_id):
        # A task's or a schedule's thread: the Board shows those, not History.
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


def _busy(exc: ConversationBusy) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": exc.detail, "running": exc.running, "connected": exc.connected},
    )


def create_conversations_router(conversations: Conversations) -> APIRouter:
    router = APIRouter(prefix="/api/conversations", tags=["conversations"])

    @router.get("", response_model=ConversationList, response_model_exclude_unset=True)
    async def list_conversations(
        limit: int = Query(LIST_LIMIT, ge=1, le=LIST_LIMIT_MAX),
        offset: int = Query(0, ge=0),
    ):
        """Past chat conversations, newest first.

        ``available`` is false (with a ``reason``) when the checkpointer can't list
        threads. ``indexing`` is true while the first scan of a large checkpoint
        database is still running: the newest conversations are already listed, and
        asking again returns the rest.
        """
        return await conversations.list(limit=limit, offset=offset)

    @router.get("/{thread_id}", response_model=ConversationDetail, response_model_exclude_unset=True)
    async def get_conversation(thread_id: str):
        """One conversation's transcript, plus whether a turn is ``running`` in it,
        another window is ``connected`` to it, and the ``interrupt`` it is paused on."""
        _check_id(thread_id)
        try:
            detail = await conversations.get(thread_id)
        except HistoryUnsupported as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from None
        if detail is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return detail

    @router.post("/{thread_id}/open", response_model=ConversationDetail, response_model_exclude_unset=True)
    async def open_conversation(
        thread_id: str,
        takeover: bool = Query(
            False, description="Make the window that has the conversation open let go of it"
        ),
    ):
        """Take a conversation over before attaching ``GET /api/stream`` to it.

        409 while a turn is running in it or another window is attached; read it
        with ``GET`` instead and try again when it is free. With ``takeover=true`` a
        window that merely has it open is told to let go (its stream ends with a
        ``superseded`` frame); a running turn is still a 409.
        """
        _check_id(thread_id)
        try:
            detail = await conversations.open(thread_id, takeover=takeover)
        except ConversationBusy as exc:
            raise _busy(exc) from None
        except HistoryUnsupported as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from None
        if detail is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return detail

    @router.delete("/{thread_id}", response_model=OkResponse, response_model_exclude_unset=True)
    async def delete_conversation(thread_id: str):
        """Delete a conversation from the checkpointer for good. 409 while a turn is
        running in it; 501 when the checkpointer can't delete threads."""
        _check_id(thread_id)
        try:
            deleted = await conversations.delete(thread_id)
        except ConversationBusy as exc:
            raise _busy(exc) from None
        except HistoryUnsupported as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from None
        if not deleted:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        release_notebook_state(thread_id)
        return {"ok": True}

    return router
