"""Skill loader — discovers and instantiates built-in tools."""

from __future__ import annotations

import logging

from autonoma.executor.sandbox import Sandbox
from autonoma.executor.tools.base import BaseTool
from autonoma.executor.tools.file_ops import FileListTool, FileReadTool, FileWriteTool
from autonoma.executor.tools.shell import ShellTool
from autonoma.executor.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)


def load_builtin_tools(
    workspace_dir: str = "workspace",
    sandbox: Sandbox | None = None,
) -> list[BaseTool]:
    """Instantiate all built-in tools.

    ``sandbox`` is required for the shell + file tools to enforce the
    configured security policy. When not provided, a default
    :class:`Sandbox` is created — useful for tests but not recommended for
    production callers.
    """
    if sandbox is None:
        sandbox = Sandbox(allowed_dirs=[workspace_dir])
    tools: list[BaseTool] = [
        WebSearchTool(),
        FileReadTool(sandbox=sandbox),
        FileWriteTool(sandbox=sandbox),
        FileListTool(sandbox=sandbox),
        ShellTool(sandbox=sandbox),
    ]
    logger.info("Loaded %d built-in tools", len(tools))
    return tools
