"""Sandbox — enforces paths, env, resource limits, and backend isolation.

The sandbox is the single security boundary between the agent loop and the
host. Every filesystem tool resolves paths through :mod:`path_safety`, and
every subprocess tool runs through :meth:`Sandbox.run_subprocess` so it gets
consistent env scrubbing, rlimits, output capping, and timeout handling.

Backends:
  - ``direct``  — Run as a subprocess of the Autonoma process with rlimits
                  and env scrubbing. Default. Fast, but only as isolated as
                  the host OS allows.
  - ``docker``  — Run inside an ephemeral container with ``--network=none``
                  and capability drops. Stronger isolation at the cost of a
                  per-call container start; see :mod:`executor.backends`.

Resource limits:
  On POSIX hosts we apply ``resource.setrlimit`` via the subprocess
  ``preexec_fn`` so a runaway child can't eat the host. On Windows the
  ``resource`` module is absent and the limits become advisory — the timeout
  and output cap still apply, but memory / CPU / nproc enforcement is
  effectively best-effort. This is logged once at startup so operators know
  which platform they're on.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence

from autonoma.executor.path_safety import (
    PathSafetyError,
    ResolvedPath,
    is_within,
    resolve_within,
)

logger = logging.getLogger(__name__)

SandboxBackend = Literal["direct", "docker"]


# Environment variables the sandbox always strips from child processes.
# Secrets go first — no tool should ever see an API key — followed by proxy
# variables that could be used to tunnel egress, and shell rc hooks that can
# execute arbitrary code on startup.
_DENY_ENV = {
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "AUTONOMA_LLM_API_KEY",
    "AUTONOMA_REST_API_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "GMAIL_APP_PASSWORD",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "BASH_ENV",
    "ENV",
    "PROMPT_COMMAND",
    "PS1",
    "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES",
}

# Minimal env an allowlist-based shell child gets when env_allowlist is empty.
# Keeps PATH so common binaries resolve, nothing else.
_DEFAULT_ENV_FALLBACK = {"PATH", "LANG", "LC_ALL", "TZ"}


@dataclass
class SandboxConfig:
    """Declarative security policy for tool execution.

    Defaults are conservative: 15s wall-clock timeout, 256 MiB memory ceiling,
    10 MB output cap, no network access for subprocess tools, no shell
    string mode, no shell binaries allowed at all (so the agent must be
    given an explicit allowlist before it can invoke anything via shell).
    """

    # Wall-clock seconds before a tool is killed.
    timeout: float = 15.0
    # Bytes of combined stdout+stderr retained per subprocess call.
    max_output_bytes: int = 10 * 1024 * 1024
    # RLIMIT_AS (address-space) ceiling for subprocess children, in MiB.
    # Honored on POSIX; ignored on Windows.
    max_memory_mb: int = 256
    # RLIMIT_CPU ceiling (CPU-seconds). 0 disables.
    max_cpu_seconds: int = 30
    # RLIMIT_NPROC for children. 0 disables.
    max_processes: int = 64
    # RLIMIT_FSIZE — per-file write ceiling, in MiB. 0 disables.
    max_file_size_mb: int = 50
    # When False, HTTP_PROXY etc. are stripped from subprocess env and the
    # shell tool refuses to invoke known network binaries even if allowed.
    allow_network: bool = False
    # Environment variables to PASS THROUGH to subprocesses. Secrets
    # (see _DENY_ENV) are always stripped even if listed here.
    env_allowlist: list[str] = field(default_factory=lambda: ["PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR"])
    # Shell tool policy — see ShellTool.
    shell_allowed_binaries: list[str] = field(default_factory=list)
    shell_allow_strings: bool = False
    # File-write policy.
    write_denied_extensions: list[str] = field(default_factory=lambda: [
        ".exe", ".bat", ".cmd", ".ps1", ".psm1",
        ".sh", ".bash", ".zsh", ".fish",
        ".so", ".dylib", ".dll",
        ".com", ".scr", ".msi",
    ])
    # Backend selection: see :mod:`executor.backends`.
    backend: SandboxBackend = "direct"
    # Per-session tool-call rate limit (calls, window_seconds). 0 disables.
    rate_limit_calls: int = 60
    rate_limit_window: float = 60.0


@dataclass
class SubprocessResult:
    """Outcome of :meth:`Sandbox.run_subprocess`."""

    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool
    truncated: bool


class Sandbox:
    """Security boundary for tool execution.

    Tools should never reach for :mod:`subprocess` or :mod:`os` directly —
    everything routes through the sandbox so that env, rlimits, and
    working-directory guarantees stay consistent across tools.
    """

    def __init__(
        self,
        allowed_dirs: list[str] | None = None,
        config: SandboxConfig | None = None,
        # Back-compat: older call sites passed `timeout=` directly. Prefer
        # constructing a SandboxConfig, but accept the shorthand so existing
        # wiring (e.g. main.py) doesn't break on upgrade.
        timeout: float | None = None,
    ):
        self._config = config or SandboxConfig()
        if timeout is not None:
            self._config.timeout = timeout
        self._allowed_dirs = [
            Path(d).resolve() for d in (allowed_dirs or ["workspace"])
        ]
        self._rlimit_warned = False

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def validate_file_path(self, path: str | Path) -> bool:
        """Return True iff *path* resolves inside any allowed directory."""
        return any(is_within(d, path) for d in self._allowed_dirs)

    def resolve_path(self, user_path: str, base_dir: str | Path | None = None) -> ResolvedPath:
        """Resolve *user_path* inside the first allowed dir (or *base_dir*).

        Raises :class:`PathSafetyError` on any escape.
        """
        base = Path(base_dir).resolve() if base_dir else self._allowed_dirs[0]
        if base_dir and not any(is_within(d, base) for d in self._allowed_dirs):
            raise PathSafetyError("base_dir is outside the sandbox")
        return resolve_within(base, user_path)

    def get_allowed_dirs(self) -> list[Path]:
        return list(self._allowed_dirs)

    # ------------------------------------------------------------------
    # Subprocess helpers
    # ------------------------------------------------------------------

    @property
    def timeout(self) -> float:
        """Back-compat shim — tool_runner / shell read `sandbox.timeout`."""
        return self._config.timeout

    @property
    def config(self) -> SandboxConfig:
        return self._config

    def build_env(self) -> dict[str, str]:
        """Build the subprocess environment.

        Starts empty, copies through the configured allowlist from the
        current process, then strips any secret/proxy keys regardless of
        whether they were listed — defense in depth against a mis-configured
        ``env_allowlist``.
        """
        env: dict[str, str] = {}
        for key in self._config.env_allowlist:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val

        # Always strip deny-listed keys.
        for key in list(env.keys()):
            if key in _DENY_ENV:
                env.pop(key, None)

        # Guarantee PATH is set so /bin/sh etc. resolve.
        if "PATH" not in env:
            env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

        # When network is disabled, clear proxy knobs regardless of allowlist.
        if not self._config.allow_network:
            for key in (
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy",
                "NO_PROXY", "no_proxy",
            ):
                env.pop(key, None)

        return env

    def _preexec(self):
        """Apply POSIX rlimits inside the forked child.

        Called as ``preexec_fn=`` — must stay small and forkserver-safe.
        On Windows this method is unreachable because ``preexec_fn`` isn't
        supported; callers pass ``preexec_fn=None`` on that platform.
        """
        try:
            import resource  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover — Windows
            return

        cfg = self._config
        if cfg.max_memory_mb > 0:
            limit = cfg.max_memory_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            except (ValueError, OSError):
                pass
        if cfg.max_cpu_seconds > 0:
            try:
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (cfg.max_cpu_seconds, cfg.max_cpu_seconds),
                )
            except (ValueError, OSError):
                pass
        if cfg.max_processes > 0:
            try:
                resource.setrlimit(
                    resource.RLIMIT_NPROC,
                    (cfg.max_processes, cfg.max_processes),
                )
            except (ValueError, OSError):
                pass
        if cfg.max_file_size_mb > 0:
            limit = cfg.max_file_size_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
            except (ValueError, OSError):
                pass
        # Kill the child if the parent dies (Linux only).
        try:
            import ctypes
            PR_SET_PDEATHSIG = 1
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.prctl(PR_SET_PDEATHSIG, 9)  # SIGKILL
        except Exception:
            pass

    async def run_subprocess(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        stdin: bytes | None = None,
    ) -> SubprocessResult:
        """Run *argv* with sandbox env + rlimits + output cap + timeout.

        ``argv`` must be a list (argv mode, no shell). Callers that want to
        run shell strings should go through :class:`ShellTool`, which does
        its own policy check and then calls this helper with ``["sh", "-c",
        script]`` if ``shell_allow_strings`` is on.
        """
        if not argv:
            return SubprocessResult(stdout="", stderr="argv is empty", returncode=None, timed_out=False, truncated=False)

        cfg = self._config
        cwd_resolved: str | None = None
        if cwd is not None:
            cwd_resolved = str(Path(cwd).resolve())
            if not self.validate_file_path(cwd_resolved):
                return SubprocessResult(
                    stdout="",
                    stderr=f"cwd outside sandbox: {cwd}",
                    returncode=None,
                    timed_out=False,
                    truncated=False,
                )
        else:
            # Default to the first allowed dir so stray relative paths don't
            # land in the caller's CWD (which is the process CWD by default).
            cwd_resolved = str(self._allowed_dirs[0])

        preexec = None
        if sys.platform != "win32":
            preexec = self._preexec
        elif not self._rlimit_warned:
            self._rlimit_warned = True
            logger.warning(
                "Running on Windows — subprocess rlimits are advisory "
                "(memory/CPU/nproc caps are not enforced)."
            )

        env = self.build_env()

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                cwd=cwd_resolved,
                env=env,
                preexec_fn=preexec,
            )
        except FileNotFoundError:
            return SubprocessResult(
                stdout="",
                stderr=f"binary not found: {argv[0]}",
                returncode=None,
                timed_out=False,
                truncated=False,
            )
        except PermissionError as e:
            return SubprocessResult(
                stdout="",
                stderr=f"permission denied: {e}",
                returncode=None,
                timed_out=False,
                truncated=False,
            )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(stdin),
                timeout=cfg.timeout,
            )
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True
            # SIGKILL — proc.kill() on POSIX, TerminateProcess on Windows.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            # Drain so the event loop doesn't leak pipes.
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            except asyncio.TimeoutError:
                stdout_b, stderr_b = b"", b""

        # Cap combined output size to avoid OOM from a gigabyte of stdout.
        max_bytes = cfg.max_output_bytes
        truncated = False
        if len(stdout_b) + len(stderr_b) > max_bytes:
            truncated = True
            # Give stdout 80% of the budget, stderr the rest — errors tend
            # to be shorter and we'd rather not drop the primary output.
            stdout_budget = int(max_bytes * 0.8)
            if len(stdout_b) > stdout_budget:
                stdout_b = stdout_b[:stdout_budget]
            remaining = max_bytes - len(stdout_b)
            if len(stderr_b) > remaining:
                stderr_b = stderr_b[:remaining]

        return SubprocessResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode,
            timed_out=timed_out,
            truncated=truncated,
        )
