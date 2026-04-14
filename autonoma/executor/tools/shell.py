"""Shell execution tool — sandboxed command runner."""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from autonoma.executor.tools.base import BaseTool

# Commands that are always blocked
BLOCKED_COMMANDS = {
    "rm", "rmdir", "mkfs", "dd", "format",
    "shutdown", "reboot", "halt", "poweroff",
    "kill", "killall", "pkill",
    "chmod", "chown", "chgrp",
    "su", "sudo", "passwd",
    "wget", "curl",  # Block raw download to prevent exfiltration
}

# Dangerous patterns in arguments
BLOCKED_PATTERNS = [
    "rm -rf",
    "rm -fr",
    "> /dev",
    ":(){ :|:& };:",  # Fork bomb
]


class ShellTool(BaseTool):
    """Execute shell commands with safety restrictions."""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "Use for tasks like running scripts, checking system info, "
            "or processing data. Dangerous commands are blocked for safety."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
            },
            "required": ["command"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        command = params.get("command", "").strip()
        if not command:
            return "Error: No command provided."

        # Safety checks
        if error := self._check_safety(command):
            return error

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )

            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                output += "\n[stderr] " + stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                output += f"\n[exit code: {proc.returncode}]"

            # Truncate long output
            if len(output) > 5_000:
                output = output[:5_000] + f"\n\n... (truncated, {len(output)} chars total)"

            return output.strip() or "(no output)"

        except asyncio.TimeoutError:
            return f"Error: Command timed out after {self._timeout}s"
        except Exception as e:
            return f"Error executing command: {e}"

    def _check_safety(self, command: str) -> str | None:
        """Return error message if command is blocked, None if safe."""
        cmd_lower = command.lower().strip()

        # Check blocked patterns
        for pattern in BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                return f"Error: Blocked dangerous pattern: {pattern}"

        # Check first word against blocked commands
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()

        if parts:
            base_cmd = parts[0].split("/")[-1]  # Handle /usr/bin/rm etc.
            if base_cmd in BLOCKED_COMMANDS:
                return f"Error: Command '{base_cmd}' is blocked for safety."

        return None
