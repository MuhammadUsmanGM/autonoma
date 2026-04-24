"""Shell execution tool — sandboxed command runner.

Security posture (strict allowlist mode is the default):

* **Argv mode only, by default.** The agent passes ``args: [binary, ...argv]``
  and we run it via ``create_subprocess_exec`` — no shell interpretation,
  so metacharacters in arguments are literal strings, not operators.
* **Binary allowlist.** Only binaries explicitly listed in
  ``sandbox.shell_allowed_binaries`` may run. Empty list = the shell tool
  is effectively disabled. This prevents a compromised agent from shelling
  out to ``netcat`` / ``python`` / ``curl`` just because the blocklist
  didn't name them.
* **Shell-string mode is opt-in.** Setting ``sandbox.shell_allow_strings:
  true`` re-enables the ``command: <string>`` input. Even then we reject
  unambiguously-dangerous metacharacters unless the binary is allowlisted
  for scripting (``sh``, ``bash``). This is the "backwards-compatible for
  power users" path; we do not recommend it.
* **Env + rlimits.** All children go through :meth:`Sandbox.run_subprocess`,
  which scrubs secrets/proxies from env and applies CPU/memory/process
  caps via ``RLIMIT_*`` on POSIX.
"""

from __future__ import annotations

import logging
import shlex
from typing import Any

from autonoma.executor.sandbox import Sandbox
from autonoma.executor.tools.base import BaseTool, ToolPermission

logger = logging.getLogger(__name__)

# Metacharacters that let a shell string break out of argv semantics.
# Only checked when the caller uses the string mode; argv mode is immune.
_SHELL_METACHARS = (";", "&", "|", "`", "$(", ">", "<", "\\\n")

# Binaries that are effectively arbitrary code execution on their own —
# even in allowlist mode we treat these as especially dangerous and require
# the operator to opt in via shell_allow_strings=true for scripting. An
# agent that needs Python should be given a proper "python" skill, not raw
# shell access.
_SCRIPTING_BINARIES = {
    "sh", "bash", "zsh", "fish", "dash", "ksh",
    "python", "python3", "python3.10", "python3.11", "python3.12",
    "perl", "ruby", "node", "nodejs", "deno",
    "pwsh", "powershell",
}

# Network-capable binaries rejected when sandbox.allow_network is False.
# The agent can still be explicitly allowlisted to use them if an operator
# really wants that — but by default, network egress through shell is off.
_NETWORK_BINARIES = {
    "curl", "wget", "nc", "ncat", "netcat", "socat",
    "ssh", "scp", "sftp", "rsync", "telnet", "ftp",
}


class ShellError(ValueError):
    """Raised when a shell invocation is rejected by policy."""


class ShellTool(BaseTool):
    """Execute shell commands with allowlist-enforced safety."""

    def __init__(self, sandbox: Sandbox):
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "shell"

    @property
    def permissions(self) -> ToolPermission:
        return ToolPermission(
            level="dangerous",
            shell=True,
            filesystem=True,
            # Network surface depends on config; we always advertise True in
            # the manifest so operators don't under-estimate the tool.
            network=True,
            description=(
                "Executes allow-listed binaries with arguments. Binaries must be "
                "enabled via sandbox.shell_allowed_binaries."
            ),
        )

    @property
    def description(self) -> str:
        cfg = self._sandbox.config
        allowed = ", ".join(cfg.shell_allowed_binaries) or "(none — shell is disabled)"
        return (
            "Execute a single binary with arguments. Pass `args` as a list "
            "where args[0] is the binary. Allowed binaries: "
            f"{allowed}. Argument strings are literal — no shell interpretation."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        # Two shapes — argv (preferred) and command string (only when enabled).
        return {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "argv list — args[0] is the binary (must be in the "
                        "allowlist), remaining items are literal arguments. "
                        "Preferred input."
                    ),
                },
                "command": {
                    "type": "string",
                    "description": (
                        "Full shell command string. Only accepted when "
                        "sandbox.shell_allow_strings is true."
                    ),
                },
            },
        }

    async def execute(self, params: dict[str, Any]) -> str:
        try:
            argv = self._build_argv(params)
        except ShellError as e:
            logger.warning("Shell invocation denied: %s", e)
            self._record_denial(str(e))
            return f"Error: {e}"

        cfg = self._sandbox.config
        if not cfg.shell_allowed_binaries:
            self._record_denial("shell disabled (no allowed binaries)")
            return (
                "Error: shell tool is disabled. Ask the operator to configure "
                "sandbox.shell_allowed_binaries in autonoma.yaml."
            )

        binary = argv[0]
        if binary not in cfg.shell_allowed_binaries:
            self._record_denial(f"binary not allow-listed: {binary}")
            return (
                f"Error: binary '{binary}' is not allow-listed. "
                f"Allowed: {', '.join(cfg.shell_allowed_binaries)}"
            )

        if not cfg.allow_network and binary in _NETWORK_BINARIES:
            self._record_denial(f"network binary blocked: {binary}")
            return (
                f"Error: '{binary}' is a network binary and sandbox.allow_network "
                f"is false."
            )

        if binary in _SCRIPTING_BINARIES and not cfg.shell_allow_strings:
            # Scripting binaries with -c /-e accept arbitrary code and
            # sidestep argv hygiene. Gate them behind shell_allow_strings.
            self._record_denial(f"scripting binary blocked: {binary}")
            return (
                f"Error: '{binary}' is a scripting interpreter; set "
                f"sandbox.shell_allow_strings: true to enable it."
            )

        logger.info("Shell exec: %s (%d argv items)", binary, len(argv))
        logger.debug("Argv: %s", argv)

        result = await self._sandbox.run_subprocess(argv)

        if result.timed_out:
            self._record_denial("timeout")
            return f"Error: Command timed out after {self._sandbox.timeout}s"

        output = result.stdout
        if result.stderr:
            output += ("\n[stderr] " + result.stderr) if output else result.stderr
        if result.returncode not in (0, None):
            output += f"\n[exit code: {result.returncode}]"
        if result.truncated:
            output += (
                f"\n\n... (truncated to {self._sandbox.config.max_output_bytes} bytes)"
            )

        return output.strip() or "(no output)"

    # ------------------------------------------------------------------
    # Input shape handling
    # ------------------------------------------------------------------

    def _build_argv(self, params: dict[str, Any]) -> list[str]:
        """Normalize the caller's input into an argv list.

        Raises :class:`ShellError` if the input is malformed or violates
        policy (shell metacharacters in string mode, etc.).
        """
        argv = params.get("args")
        if argv is not None:
            if not isinstance(argv, list) or not argv:
                raise ShellError("`args` must be a non-empty list of strings")
            if not all(isinstance(a, str) for a in argv):
                raise ShellError("`args` items must all be strings")
            if not argv[0]:
                raise ShellError("`args[0]` (binary) is empty")
            # Basename — we allow "python3" even if the allowlist has "python3"
            # but block full-path invocations that could bypass PATH
            # resolution (e.g. "/tmp/evil/python3").
            bin_name = argv[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if bin_name != argv[0] and "/" in argv[0]:
                raise ShellError(
                    "`args[0]` must be a bare binary name (no directory path); "
                    "use PATH-resolved names like 'ls' not '/usr/bin/ls'."
                )
            return [bin_name, *argv[1:]]

        command = params.get("command")
        if command is None:
            raise ShellError("Provide either `args` (preferred) or `command`")
        if not self._sandbox.config.shell_allow_strings:
            raise ShellError(
                "shell string mode is disabled — pass `args: [binary, ...]` instead"
            )
        command = command.strip()
        if not command:
            raise ShellError("`command` is empty")

        for meta in _SHELL_METACHARS:
            if meta in command:
                raise ShellError(
                    f"command contains shell metacharacter {meta!r}; pipes, "
                    f"redirects, and command substitution are disabled. Use "
                    f"`args` list instead."
                )

        try:
            parts = shlex.split(command)
        except ValueError as e:
            raise ShellError(f"could not parse command: {e}") from e
        if not parts:
            raise ShellError("command parsed to empty argv")
        # Block absolute paths in string mode too.
        if "/" in parts[0] or "\\" in parts[0]:
            raise ShellError("binary must be a bare name, not a path")
        return parts

    @staticmethod
    def _record_denial(reason: str) -> None:
        from autonoma.observability.metrics import record_sandbox_denial
        record_sandbox_denial("shell", reason)
