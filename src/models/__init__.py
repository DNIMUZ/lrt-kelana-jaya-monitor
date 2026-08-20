from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SignalCategory(str, Enum):
	NORMAL = "normal"
	CROWDING = "crowding"
	DELAY = "delay"
	DISRUPTION = "disruption"
	OTHER = "other"


class StatusLevel(str, Enum):
	NORMAL = "normal"
	MODERATE = "moderate"
	BUSY = "busy"
	VERY_BUSY = "very_busy"
	DISRUPTION = "disruption"


@dataclass(frozen=True)
class PublicSignal:
	text: str
	category: SignalCategory
	station: str | None = None
	observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
	source: str = "public_report"
	independent_author: bool = True
	author_id: str | None = None


@dataclass(frozen=True)
class OfficialFact:
	service_operating: bool = True
	train_count: int | None = None
	disruption_message: str | None = None
	observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class StatusEstimate:
	level: StatusLevel
	crowding_score: float
	confidence: float
	rationale: list[str]
	generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
