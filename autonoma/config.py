"""Configuration loader for Autonoma."""

from __future__ import annotations

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


@dataclass
class Config:
    name: str = "Autonoma"
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
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

    config = Config(
        name=data.get("name", "Autonoma"),
        gateway=GatewayConfig(**gateway_data),
        llm=LLMConfig(**{k: v for k, v in llm_data.items() if v is not None}),
        workspace_dir=data.get("workspace_dir", "workspace"),
        session_dir=data.get("session_dir", ".session"),
        log_level=data.get("log_level", "INFO"),
    )

    # Override LLM API key from environment
    api_key = os.getenv("AUTONOMA_LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or ""
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

    return config
