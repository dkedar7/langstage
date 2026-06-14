"""Web-stage task persistence: a durable SQLite-backed task store.

The task-delegation *engine* (TaskRunner, the TaskStore protocol, the
Task/TaskState machine) lives in the shared core,
``langgraph_stream_parser.tasks``. This package provides only langstage-web's
concrete store — durable across restarts so the task board survives a bounce.
"""
from .sqlite_store import SqliteTaskStore

__all__ = ["SqliteTaskStore"]
