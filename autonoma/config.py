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
class RelationshipConfig:
    """Per-contact relationship tiering.

    Drives tone calibration: a stranger gets a formal terse reply, a VIP
    gets a polished thorough one. Tier is computed from message history
    plus explicit overrides from this config.
    """

    enabled: bool = True
    db_path: str = ".memory/contacts.db"
    default_tier: str = "stranger"
    # Address / phone / handle exact matches always classified as VIP.
    vip_addresses: list[str] = field(default_factory=list)
    # Substring patterns in display_name or signature that escalate to VIP.
    vip_keywords: list[str] = field(default_factory=list)
    # Message-count thresholds: <stranger_max ⇒ stranger, <colleague_min ⇒ acquaintance
    stranger_max_messages: int = 1
    colleague_min_messages: int = 6


@dataclass
class ConversationStateConfig:
    """State machine that tracks awaiting/resolved/snoozed per contact."""

    enabled: bool = True
    db_path: str = ".memory/conversation_state.db"
    # If a user message has gone unanswered this long, transition to followup_needed.
    awaiting_reply_ttl_hours: int = 72
    # Default snooze duration when no explicit deadline given.
    snooze_default_hours: int = 24
    # How often the followup scheduler scans for due nudges.
    followup_check_interval_seconds: int = 3600


@dataclass
class TriageConfig:
    """Pre-agent triage policy.

    Filters inbound messages so the agent doesn't reply to noreply addresses,
    newsletters, auto-confirmations, broadcast spam, etc. Layer 1 is
    deterministic rules (free); Layer 2 is an optional cheap LLM classifier
    for ambiguous cases.
    """

    enabled: bool = True
    # When true, ambiguous messages that pass Layer 1 are sent to a small
    # LLM for classification. Costs one cheap inference per uncached sender.
    llm_classifier_enabled: bool = False
    # Model slug used for the Layer 2 classifier. Should be small/cheap.
    classifier_model: str = ""
    # How long a per-sender decision is cached, in seconds. Newsletters from
    # the same address within this window won't be re-classified.
    sender_cache_ttl: int = 86400
    # When a message is filtered (ignore/archive), still append a one-line
    # entry to the daily memory log so the user has a record.
    archive_to_memory: bool = True
    # When a decision is "escalate", surface a HUD alert instead of replying.
    escalate_to_dashboard: bool = True


@dataclass
class GoogleCalendarConnectorConfig:
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    scopes: list[str] = field(default_factory=lambda: [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    ])


@dataclass
class OneDriveConnectorConfig:
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    # `common` supports both personal MSA and work/school accounts.
    tenant: str = "common"
    scopes: list[str] = field(default_factory=lambda: [
        "offline_access",
        "User.Read",
        "Files.ReadWrite",
    ])


@dataclass
class ConnectorsConfig:
    """Third-party connectors (Google Calendar, OneDrive, ...)."""

    db_path: str = "workspace/connectors.db"
    key_path: str = "workspace/.connector_key"
    # Public base URL the OAuth provider should redirect to. Defaults to the
    # local gateway HTTP port; override when running behind a tunnel.
    redirect_base_url: str = ""
    google_calendar: GoogleCalendarConnectorConfig = field(
        default_factory=GoogleCalendarConnectorConfig
    )
    onedrive: OneDriveConnectorConfig = field(default_factory=OneDriveConnectorConfig)


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
    triage: TriageConfig = field(default_factory=TriageConfig)
    relationship: RelationshipConfig = field(default_factory=RelationshipConfig)
    conversation_state: ConversationStateConfig = field(default_factory=ConversationStateConfig)
    connectors: ConnectorsConfig = field(default_factory=ConnectorsConfig)
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
    triage_data = data.get("triage", {})
    relationship_data = data.get("relationship", {})
    conversation_state_data = data.get("conversation_state", {})
    connectors_data = data.get("connectors", {}) or {}

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
        triage=TriageConfig(
            **{k: v for k, v in triage_data.items() if v is not None}
        ),
        relationship=RelationshipConfig(
            **{k: v for k, v in relationship_data.items() if v is not None}
        ),
        conversation_state=ConversationStateConfig(
            **{k: v for k, v in conversation_state_data.items() if v is not None}
        ),
        connectors=_load_connectors_config(connectors_data),
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

    # --- Triage overrides ---

    if (triage_env := os.getenv("AUTONOMA_TRIAGE_ENABLED")) is not None:
        config.triage.enabled = triage_env.lower() not in ("0", "false", "no", "off", "")
    if (clf_env := os.getenv("AUTONOMA_TRIAGE_LLM_CLASSIFIER")) is not None:
        config.triage.llm_classifier_enabled = clf_env.lower() not in (
            "0", "false", "no", "off", ""
        )
    if model := os.getenv("AUTONOMA_TRIAGE_MODEL"):
        config.triage.classifier_model = model

    # --- Relationship / state overrides ---

    if (rel_env := os.getenv("AUTONOMA_RELATIONSHIP_ENABLED")) is not None:
        config.relationship.enabled = rel_env.lower() not in ("0", "false", "no", "off", "")
    if vips := os.getenv("AUTONOMA_VIP_ADDRESSES"):
        config.relationship.vip_addresses = [v.strip() for v in vips.split(",") if v.strip()]
    if (state_env := os.getenv("AUTONOMA_STATE_ENABLED")) is not None:
        config.conversation_state.enabled = state_env.lower() not in ("0", "false", "no", "off", "")

    # --- Connector overrides ---

    if cid := os.getenv("GOOGLE_CLIENT_ID"):
        config.connectors.google_calendar.client_id = cid
    if cs := os.getenv("GOOGLE_CLIENT_SECRET"):
        config.connectors.google_calendar.client_secret = cs
    if (gc_env := os.getenv("AUTONOMA_GCAL_ENABLED")) is not None:
        config.connectors.google_calendar.enabled = gc_env.lower() not in (
            "0", "false", "no", "off", ""
        )
    if cid := os.getenv("MS_CLIENT_ID"):
        config.connectors.onedrive.client_id = cid
    if cs := os.getenv("MS_CLIENT_SECRET"):
        config.connectors.onedrive.client_secret = cs
    if tenant := os.getenv("MS_TENANT"):
        config.connectors.onedrive.tenant = tenant
    if (od_env := os.getenv("AUTONOMA_ONEDRIVE_ENABLED")) is not None:
        config.connectors.onedrive.enabled = od_env.lower() not in (
            "0", "false", "no", "off", ""
        )
    if base := os.getenv("AUTONOMA_CONNECTOR_REDIRECT_BASE"):
        config.connectors.redirect_base_url = base

    return config


def _load_connectors_config(data: dict) -> ConnectorsConfig:
    """Build :class:`ConnectorsConfig` from a YAML sub-dict."""
    gc = data.get("google_calendar", {}) or {}
    od = data.get("onedrive", {}) or {}
    return ConnectorsConfig(
        db_path=data.get("db_path", "workspace/connectors.db"),
        key_path=data.get("key_path", "workspace/.connector_key"),
        redirect_base_url=data.get("redirect_base_url", ""),
        google_calendar=GoogleCalendarConnectorConfig(
            **{k: v for k, v in gc.items() if v is not None}
        ),
        onedrive=OneDriveConnectorConfig(
            **{k: v for k, v in od.items() if v is not None}
        ),
    )


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
