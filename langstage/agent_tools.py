"""Best-effort agent tool introspection helpers."""


def agent_tool_names(agent) -> set[str] | None:
    """Pull bound tool names out of a compiled graph when possible."""
    try:
        names: set[str] = set()

        def add_from_tools(tools) -> None:
            for tool in tools or ():
                name = getattr(tool, "name", getattr(tool, "__name__", ""))
                if name:
                    names.add(name)

        for owner in (agent, getattr(agent, "builder", None)):
            for attr in ("middleware", "_middleware"):
                for middleware in getattr(owner, attr, None) or ():
                    add_from_tools(getattr(middleware, "tools", None))

        nodes = getattr(agent, "nodes", None) or {}
        for node in nodes.values():
            target = getattr(node, "bound", node)
            tbn = getattr(target, "tools_by_name", None)
            if isinstance(tbn, dict):
                names.update(tbn.keys())
        return names or None
    except Exception:  # noqa: BLE001 - graph internals differ across integrations
        return None
