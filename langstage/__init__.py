"""LangStage — the web stage for your LangGraph agent."""

from importlib.metadata import PackageNotFoundError, version

from langstage_core.tasks import TASK_TOOLS

from langstage.app import CoworkApp, run_app
from langstage.scheduler import CRON_TOOLS

#: One-import bundle of host-provided agent tools. Add to a bring-your-own agent
#: to unlock agent-driven scheduling + async task self-delegation:
#:
#:     from langstage import LANGSTAGE_TOOLS
#:     agent = create_deep_agent(tools=[*my_tools, *LANGSTAGE_TOOLS], ...)
#:
#: The tools reach the host's process-global scheduler/runner at request time,
#: so they only do anything when served by LangStage (no-op otherwise).
LANGSTAGE_TOOLS = [*CRON_TOOLS, *TASK_TOOLS]

try:
    __version__ = version("langstage")
except PackageNotFoundError:  # pragma: no cover - editable/source checkout
    __version__ = "0.0.0+local"

__all__ = ["CoworkApp", "run_app", "LANGSTAGE_TOOLS"]
