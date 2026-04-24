"""Configuration loader for Autonoma."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    api_key: str = ""
    model: str = "claude-sonnet-4-6"


@dataclass
class GatewayConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    http_port: int = 8766


@dataclass
class TelegramConfig:
    bot_token: str = ""
    proxy_url: str = ""  # e.g. socks5://127.0.0.1:1080 or http://127.0.0.1:8080
    enabled: bool = False


@dataclass
class DiscordConfig:
    bot_token: str = ""
    enabled: bool = False


@dataclass
class WhatsAppConfig:
    bridge_url: str = "http://localhost:3001"
    webhook_path: str = "/webhook/whatsapp"
    enabled: bool = False
    # When true, the WhatsApp adapter auto-spawns the whatsapp-bridge Node
    # sidecar on start() and stops it on shutdown. Users running their own
    # bridge (e.g. on a remote host, or via PM2/systemd) can set this to
    # false to keep the old BYO-bridge behavior.
    auto_spawn_bridge: bool = True
    # Where to find whatsapp-bridge/. Default is <repo-root>/whatsapp-bridge
    # relative to the autonoma package; override if the sidecar lives
    # elsewhere (e.g. an npm-installed Autonoma with the bridge vendored
    # at a different path).
    bridge_dir: str = ""


@dataclass
class GmailConfig:
    email_address: str = ""
    app_password: str = ""
    imap_host: str = "imap.gmail.com"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    poll_interval: int = 30
    enabled: bool = False


@dataclass
class RESTConfig:
    enabled: bool = True
    api_token: str = ""


@dataclass
class ChannelsConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    rest: RESTConfig = field(default_factory=RESTConfig)


@dataclass
class MemoryConfig:
    db_path: str = ".memory/autonoma.db"
    max_context_memories: int = 15
    decay_interval: int = 3600  # seconds between consolidation cycles
    importance_threshold: float = 0.1  # archive below this
    decay_factor: float = 0.95
    consolidation_enabled: bool = True


@dataclass
class SandboxSettings:
    """Security policy for the executor sandbox.

    Mirrors :class:`autonoma.executor.sandbox.SandboxConfig` so users can
    tune the sandbox from ``autonoma.yaml`` without reaching into Python
    code. Defaults match the conservative posture in SandboxConfig.
    """

    timeout: float = 15.0
    max_output_bytes: int = 10 * 1024 * 1024
    max_memory_mb: int = 256
    max_cpu_seconds: int = 30
    max_processes: int = 64
    max_file_size_mb: int = 50
    allow_network: bool = False
    env_allowlist: list[str] = field(default_factory=lambda: ["PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR"])
    shell_allowed_binaries: list[str] = field(default_factory=list)
    shell_allow_strings: bool = False
    write_denied_extensions: list[str] = field(default_factory=lambda: [
        ".exe", ".bat", ".cmd", ".ps1", ".psm1",
        ".sh", ".bash", ".zsh", ".fish",
        ".so", ".dylib", ".dll",
        ".com", ".scr", ".msi",
    ])
    backend: str = "direct"
    rate_limit_calls: int = 60
    rate_limit_window: float = 60.0


@dataclass
class ObservabilityConfig:
    # "text" (human-readable, default) or "json" (one JSON object per line)
    log_format: str = "text"
    # When true, HTTP server exposes /metrics in Prometheus text exposition format.
    metrics_enabled: bool = True
    # OpenTelemetry OTLP/HTTP endpoint (e.g. "http://localhost:4318/v1/traces").
    # Empty = disabled. Requires the `opentelemetry-sdk` optional dep to be
    # installed; if it's missing we log once and continue without OTel.
    otel_endpoint: str = ""
    otel_service_name: str = "autonoma"
    # Optional comma-separated headers appended to OTLP requests
    # (e.g. "x-api-key=abc,x-tenant=acme"). Used by hosted collectors.
    otel_headers: str = ""


@dataclass
class Config:
    name: str = "Autonoma"
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    channels: ChannelsConfig = field(default_factory=ChannelsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)
    workspace_dir: str = "workspace"
    session_dir: str = ".session"
    log_level: str = "INFO"


def load_config(config_path: str | None = None) -> Config:
    """Load config with precedence: env vars > .env > YAML > defaults."""
    load_dotenv()

    data: dict = {}
    path = Path(config_path) if config_path else Path("autonoma.yaml")
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}

    # Build nested config from YAML data
    gateway_data = data.get("gateway", {})
    llm_data = data.get("llm", {})
    observability_data = data.get("observability", {})
    sandbox_data = data.get("sandbox", {})

    config = Config(
        name=data.get("name", "Autonoma"),
        gateway=GatewayConfig(**gateway_data),
        llm=LLMConfig(**{k: v for k, v in llm_data.items() if v is not None}),
        observability=ObservabilityConfig(
            **{k: v for k, v in observability_data.items() if v is not None}
        ),
        sandbox=SandboxSettings(
            **{k: v for k, v in sandbox_data.items() if v is not None}
        ),
        workspace_dir=data.get("workspace_dir", "workspace"),
        session_dir=data.get("session_dir", ".session"),
        log_level=data.get("log_level", "INFO"),
    )

    # Override LLM API key from environment (check provider-specific keys too)
    api_key = (
        os.getenv("AUTONOMA_LLM_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or ""
    )
    if api_key:
        config.llm.api_key = api_key

    # Override LLM provider/model from environment
    if provider := os.getenv("AUTONOMA_LLM_PROVIDER"):
        config.llm.provider = provider
    if model := os.getenv("AUTONOMA_LLM_MODEL"):
        config.llm.model = model

    # Override log level from environment
    if log_level := os.getenv("AUTONOMA_LOG_LEVEL"):
        config.log_level = log_level

    # --- Channel auto-enable from env vars ---

    if token := os.getenv("TELEGRAM_BOT_TOKEN"):
        config.channels.telegram.bot_token = token
        config.channels.telegram.enabled = True
    if proxy := os.getenv("TELEGRAM_PROXY_URL"):
        config.channels.telegram.proxy_url = proxy

    if token := os.getenv("DISCORD_BOT_TOKEN"):
        config.channels.discord.bot_token = token
        config.channels.discord.enabled = True

    if bridge_url := os.getenv("WHATSAPP_BRIDGE_URL"):
        config.channels.whatsapp.bridge_url = bridge_url
        config.channels.whatsapp.enabled = True

    email_addr = os.getenv("GMAIL_ADDRESS", "")
    app_pw = os.getenv("GMAIL_APP_PASSWORD", "")
    if email_addr and app_pw:
        config.channels.gmail.email_address = email_addr
        config.channels.gmail.app_password = app_pw
        config.channels.gmail.enabled = True

    if token := os.getenv("AUTONOMA_REST_API_TOKEN"):
        config.channels.rest.api_token = token

    # --- Observability overrides ---

    if log_format := os.getenv("AUTONOMA_LOG_FORMAT"):
        config.observability.log_format = log_format.lower()
    if (metrics_env := os.getenv("AUTONOMA_METRICS_ENABLED")) is not None:
        config.observability.metrics_enabled = metrics_env.lower() not in (
            "0", "false", "no", "off", ""
        )
    if endpoint := os.getenv("AUTONOMA_OTEL_ENDPOINT"):
        config.observability.otel_endpoint = endpoint
    if service_name := os.getenv("AUTONOMA_OTEL_SERVICE_NAME"):
        config.observability.otel_service_name = service_name
    if headers := os.getenv("AUTONOMA_OTEL_HEADERS"):
        config.observability.otel_headers = headers

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Returns the modified base."""
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def save_yaml_config(path: str | Path, updates: dict) -> None:
    """Deep-merge updates into autonoma.yaml (creating it if needed) and write back.

    The caller's `updates` dict is not mutated; `_deep_merge` modifies only
    the freshly loaded `existing` copy.
    """
    p = Path(path)
    existing: dict = {}
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}
    merged = _deep_merge(existing, copy.deepcopy(updates))
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, default_flow_style=False, sort_keys=False)
