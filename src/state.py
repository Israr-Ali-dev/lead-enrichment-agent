"""State schema for the lead enrichment pipeline.

The pipeline moves a record through an explicit state machine:

    received -> enriching -> validating -> (accepted | needs_review | rejected)

`LeadState` is the single object threaded through every LangGraph node. Each
node reads it, does its work, and calls `transition()` to record what changed
and why -- `history` is a full audit trail of a record's journey.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    RECEIVED = "received"
    ENRICHING = "enriching"
    VALIDATING = "validating"
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class LeadState(BaseModel):
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Raw input
    name: str
    domain: str | None = None
    raw_notes: str | None = None

    # Pipeline state
    status: Status = Status.RECEIVED
    source_data: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = 0.0
    conflicts: list[str] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)

    def transition(self, to_state: Status, reason: str) -> None:
        """Move to a new status and append an audit entry to history."""
        self.history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "from_state": self.status.value,
                "to_state": to_state.value,
                "reason": reason,
            }
        )
        self.status = to_state
