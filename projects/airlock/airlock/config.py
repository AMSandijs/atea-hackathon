"""Validated policy loading for Airlock."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Tiers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block: list[str] = Field(default_factory=list)
    swap: list[str] = Field(default_factory=list)
    pass_: list[str] = Field(default_factory=list, alias="pass")


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_min_score: float = 0.55
    review_below: float = 0.80
    entropy_min_bits: float = 3.6
    entropy_min_length: int = 20


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    name: str
    max_span_chars: int = 4000


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    endpoint_env: str
    api_key_env: str
    model: str


class InvestigationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_claim_seconds: int = Field(default=300, ge=30, le=900)
    request_deadline_minutes: int = Field(default=30, ge=5, le=60)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int
    tiers: Tiers
    thresholds: Thresholds
    model: ModelConfig
    gateway: GatewayConfig
    investigation: InvestigationConfig = Field(default_factory=InvestigationConfig)

    @field_validator("version")
    @classmethod
    def version_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("version must be at least 1")
        return value


def load_policy(path: Path | str | None = None) -> Policy:
    """Load and validate a YAML policy, defaulting to the project policy file."""

    policy_path = Path(path) if path is not None else Path(__file__).parent.parent / "policy.yaml"
    try:
        raw: Any = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        return Policy.model_validate(raw)
    except FileNotFoundError as exc:
        raise ValueError(f"policy file not found: {policy_path}") from exc
    except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid policy at {policy_path}: {exc}") from exc
