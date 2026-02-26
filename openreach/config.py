"""Configuration management for OpenReach."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path.home() / ".openreach"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "provider": "openrouter",
        "model": "qwen/qwen3-235b-a22b-2507",
        "temperature": 0.4,
        "base_url": "",
        "openrouter_api_key": "",
        "ollama_model": "qwen3:4b",
        "ollama_base_url": "http://localhost:11434",
        "max_tokens": 4096,
        "max_turns": 50,
    },
    "browser": {
        "headless": False,
        "slow_mo": 50,
    },
    "outreach": {
        "delay_min": 45,
        "delay_max": 180,
        "daily_limit": 50,
        "session_limit": 15,
    },
    "platforms": {
        "instagram": {
            "username": "",
            "password": "",
        },
    },
    "cormass": {
        "api_key": "",
        "base_url": "https://cormass.com/wp-json/leads/v1",
    },
    "ui": {
        "host": "127.0.0.1",
        "port": 5000,
        "debug": False,
    },
    "data": {
        "db_path": str(CONFIG_DIR / "openreach.db"),
    },
}


def load_config() -> dict[str, Any]:
    """Load configuration from disk, merging with defaults."""
    config = _deep_copy(DEFAULT_CONFIG)

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        _deep_merge(config, user_config)

    # Environment variable overrides
    env_api_key = os.environ.get("OPENREACH_API_KEY")
    if env_api_key:
        config["cormass"]["api_key"] = env_api_key

    env_model = os.environ.get("OPENREACH_LLM_MODEL")
    if env_model:
        config["llm"]["model"] = env_model

    env_openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if env_openrouter_key:
        config["llm"]["openrouter_api_key"] = env_openrouter_key

    env_provider = os.environ.get("OPENREACH_LLM_PROVIDER")
    if env_provider:
        config["llm"]["provider"] = env_provider

    return _validate_config(config)


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate and clamp config values to safe ranges (Item 26)."""
    llm = config.get("llm", {})
    # Validate provider
    if llm.get("provider") not in ("openrouter", "ollama"):
        llm["provider"] = "openrouter"
    # Clamp numeric values
    llm["temperature"] = max(0.0, min(2.0, float(llm.get("temperature", 0.4))))
    llm["max_tokens"] = max(256, min(32768, int(llm.get("max_tokens", 4096))))
    llm["max_turns"] = max(1, min(500, int(llm.get("max_turns", 50))))

    outreach = config.get("outreach", {})
    outreach["delay_min"] = max(5, min(600, int(outreach.get("delay_min", 45))))
    outreach["delay_max"] = max(outreach["delay_min"], min(900, int(outreach.get("delay_max", 180))))
    outreach["daily_limit"] = max(1, min(1000, int(outreach.get("daily_limit", 50))))
    outreach["session_limit"] = max(1, min(500, int(outreach.get("session_limit", 15))))

    ui = config.get("ui", {})
    ui["port"] = max(1, min(65535, int(ui.get("port", 5000))))

    return config


def save_config_value(key: str, value: str) -> None:
    """Save a single configuration value using dot notation (e.g., 'cormass.api_key')."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config: dict[str, Any] = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # Handle flat keys like "api_key" -> "cormass.api_key"
    if key == "api_key":
        key = "cormass.api_key"

    parts = key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def _deep_copy(d: dict[str, Any]) -> dict[str, Any]:
    """Deep copy a dict of primitives."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _deep_copy(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Merge override into base in place."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
