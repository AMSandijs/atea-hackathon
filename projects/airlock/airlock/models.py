"""Core data shapes shared by the Airlock pipeline."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    entity_type: str
    text: str
    start: int
    end: int
    detector: str
    score: float
    tier: str = "swap"


@dataclass
class Sanitized:
    text: str
    findings: list[Finding]
    mapping: dict[str, str]
    blocked: list[Finding]
    low_confidence: list[Finding]


@dataclass
class AirlockResult:
    answer: str
    sanitized: Sanitized
    sent: str
    received: str
    unmapped: list[str]
    latency_ms: dict[str, int] = field(default_factory=dict)
