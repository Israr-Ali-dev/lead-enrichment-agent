"""When the enrichment source disagrees with the record's own domain, the
guardrail must flag it as a conflict, route to needs_review (not silently
accept one side), and the specific conflict must show up in the structured
log trace so a human reviewer can see exactly why."""

import logging

from src.orchestrator import run_pipeline
from src.state import Status


def test_domain_conflict_routes_to_needs_review_and_is_logged(monkeypatch, caplog):
    def fake_enrich_company(name, domain=None, timeout=5.0):
        return {"candidates": [{"name": "Acme Corp", "domain": "acme-industries.com", "logo": None}]}

    monkeypatch.setattr("src.orchestrator.enrich_company", fake_enrich_company)

    orchestrator_logger = logging.getLogger("lead_enrichment.orchestrator")
    orchestrator_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="lead_enrichment.orchestrator")

    result = run_pipeline({"name": "Acme Corp", "domain": "acme-corp.io"})

    assert result.status == Status.NEEDS_REVIEW
    assert any(c.startswith("domain_mismatch") for c in result.conflicts)

    logged_conflict = [
        record
        for record in caplog.records
        if "domain_mismatch" in getattr(record, "reason", "")
    ]
    assert logged_conflict, "expected the domain_mismatch conflict to appear in the structured log trace"
    assert "acme-corp.io" in logged_conflict[0].reason
    assert "acme-industries.com" in logged_conflict[0].reason
