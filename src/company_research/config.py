from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).parent.parent.parent  # repo root


def _load_yaml(name: str) -> dict[str, Any]:
    path = _ROOT / "config" / name
    with open(path) as f:
        return yaml.safe_load(f)


class Settings:
    def __init__(self) -> None:
        self._profiles = _load_yaml("research_profiles.yaml")
        self._source_priority = _load_yaml("source_priority.yaml")

    @property
    def anthropic_api_key(self) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        return key

    @property
    def model_id(self) -> str:
        return os.environ.get("COMPANY_RESEARCH_MODEL", "claude-sonnet-4-6")

    @property
    def edgar_user_agent(self) -> str:
        return os.environ.get(
            "EDGAR_USER_AGENT", "auto-dd openclawyi@gmail.com"
        )

    def profile(self, depth: str) -> dict[str, Any]:
        profiles = self._profiles.get("profiles", {})
        if depth not in profiles:
            raise ValueError(f"Unknown depth '{depth}'. Choose: quick, standard, deep")
        return profiles[depth]

    def source_tiers(self) -> dict[int, dict[str, Any]]:
        return {int(k): v for k, v in self._source_priority.get("tiers", {}).items()}

    def adapter_order(self) -> list[str]:
        return self._source_priority.get("adapter_order", [])

    def config_hash(self) -> str:
        data = json.dumps(
            {"profiles": self._profiles, "source_priority": self._source_priority},
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]


settings = Settings()
