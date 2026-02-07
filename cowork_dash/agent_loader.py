"""Load agent from a path:object spec string."""

import importlib.util
import sys
from pathlib import Path


def load_agent_from_spec(spec: str):
    """Load a LangGraph agent from a 'path:object' spec string.

    Args:
        spec: String like "my_agent.py:agent" or "my_module:graph".

    Returns:
        The agent object (typically a CompiledStateGraph).

    Raises:
        ValueError: If spec format is invalid.
        FileNotFoundError: If the module file doesn't exist.
        AttributeError: If the object is not found in the module.
    """
    if ":" not in spec:
        raise ValueError(
            f"Invalid agent spec '{spec}'. "
            "Expected format: 'path/to/module.py:object_name' or 'module.name:object_name'"
        )

    module_path, obj_name = spec.rsplit(":", 1)

    # Try as file path first
    file_path = Path(module_path)
    if file_path.exists() and file_path.suffix == ".py":
        module_name = file_path.stem
        spec_obj = importlib.util.spec_from_file_location(module_name, file_path)
        if spec_obj is None or spec_obj.loader is None:
            raise ImportError(f"Cannot load module from {file_path}")
        module = importlib.util.module_from_spec(spec_obj)
        sys.modules[module_name] = module
        spec_obj.loader.exec_module(module)
    else:
        # Try as dotted module path
        module = importlib.import_module(module_path)

    if not hasattr(module, obj_name):
        raise AttributeError(
            f"Module '{module_path}' has no attribute '{obj_name}'"
        )

    return getattr(module, obj_name)
