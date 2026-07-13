"""Structured (JSON lines) logging for the pipeline.

Every state transition -- including every guardrail decision, since a
guardrail decision in this pipeline always *is* a transition (its reason
string says exactly why) -- is emitted as one JSON object per line via
`log_transition`. This makes it possible to reconstruct a single record's
full journey by grepping stdout/log file for its record_id.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.state import LeadState

_RESERVED_KEYS = set(vars(logging.makeLogRecord({})).keys())


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_KEYS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_transition(logger: logging.Logger, state: LeadState) -> None:
    """Log the most recent entry in state.history for this record."""
    entry = state.history[-1]
    logger.info(
        "state_transition",
        extra={
            "record_id": state.record_id,
            "from_state": entry["from_state"],
            "to_state": entry["to_state"],
            "reason": entry["reason"],
        },
    )
