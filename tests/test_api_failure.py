"""The enrichment tool calls a real external HTTP endpoint. If it times out,
errors, or returns garbage, the pipeline must not crash or silently drop the
record -- it must route to a defined state and keep the error detail."""

import httpx

from src.orchestrator import run_pipeline
from src.state import Status


def test_enrichment_timeout_does_not_crash_and_routes_to_needs_review(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr("src.tools.enrichment.httpx.get", fake_get)

    result = run_pipeline({"name": "Whatever Inc", "domain": "whatever.com"})

    assert result.status == Status.NEEDS_REVIEW
    assert result.source_data.get("error") == "timeout"
    assert "simulated timeout" in result.source_data.get("detail", "")
    assert any("enrichment_service_error:timeout" in h["reason"] for h in result.history)
