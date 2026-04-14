"""Skill loader — discovers and instantiates built-in tools."""

from __future__ import annotations

import logging

from autonoma.executor.tools.base import BaseTool
from autonoma.executor.tools.file_ops import FileListTool, FileReadTool, FileWriteTool
from autonoma.executor.tools.shell import ShellTool
from autonoma.executor.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)


def load_builtin_tools(workspace_dir: str = "workspace") -> list[BaseTool]:
    """Instantiate all built-in tools."""
    tools: list[BaseTool] = [
        WebSearchTool(),
        FileReadTool(sandbox_dir=workspace_dir),
        FileWriteTool(sandbox_dir=workspace_dir),
        FileListTool(sandbox_dir=workspace_dir),
        ShellTool(timeout=30.0),
    ]
    logger.info("Loaded %d built-in tools", len(tools))
    return tools
