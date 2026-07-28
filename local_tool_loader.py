"""Load local AgentScope tools declared inside agent_service skills."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from agentscope.tool import FunctionTool

logger = logging.getLogger(__name__)


def _iter_tool_module_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for filename in ("tools.py", "local_tools.py"):
        path = skill_dir / filename
        if path.is_file():
            files.append(path)
    for dirname in ("tools", "local_tools"):
        path = skill_dir / dirname
        if not path.is_dir():
            continue
        files.extend(sorted(item for item in path.glob("*.py") if item.name != "__init__.py"))
    return files


def _load_module(module_file: Path, *, index: int) -> Any | None:
    module_name = f"agent_service_skill_local_tool_{index}_{abs(hash(str(module_file.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, module_file)
    if spec is None or spec.loader is None:
        logger.warning("Skip local tool module without import spec: %s", module_file)
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        logger.exception("Load local tool module failed: %s", module_file)
        return None
    return module


def _declared_tools(module: Any) -> list[Callable[..., Any]]:
    declared = getattr(module, "LOCAL_TOOLS", None)
    if declared is None:
        declared = getattr(module, "TOOLS", None)
    if declared is None:
        return []
    if callable(declared):
        declared = declared()
    tools: list[Callable[..., Any]] = []
    for item in declared or []:
        if callable(item):
            tools.append(item)
        else:
            logger.warning("Skip non-callable local tool declaration: %r", item)
    return tools


def load_skill_local_tools(skill_dirs: list[str]) -> list[FunctionTool]:
    """Load FunctionTool objects declared by skill-local Python modules."""
    loaded: list[FunctionTool] = []
    seen_names: set[str] = set()
    module_index = 0

    for raw_dir in skill_dirs or []:
        skill_dir = Path(raw_dir)
        if not skill_dir.is_dir():
            continue
        for module_file in _iter_tool_module_files(skill_dir):
            module_index += 1
            module = _load_module(module_file, index=module_index)
            if module is None:
                continue
            for func in _declared_tools(module):
                raw_tool_name = getattr(func, "__name__", None)
                tool_name = raw_tool_name if isinstance(raw_tool_name, str) else func.__class__.__name__
                if not tool_name or tool_name.startswith("_"):
                    logger.warning("Skip unnamed/private local tool from %s: %r", module_file, func)
                    continue
                if tool_name in seen_names:
                    logger.warning("Skip duplicate local tool name=%s from %s", tool_name, module_file)
                    continue
                seen_names.add(tool_name)
                loaded.append(FunctionTool(func, name=tool_name))
                logger.info("Loaded skill local tool: %s from %s", tool_name, module_file)

    return loaded
