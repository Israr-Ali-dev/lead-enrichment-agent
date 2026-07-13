"""A clean record with a single, high-confidence, domain-matching candidate
should sail through the pipeline and land in `accepted` with no conflicts."""

from src.orchestrator import run_pipeline
from src.state import Status


def test_happy_path_clean_record_is_accepted(monkeypatch):
    def fake_enrich_company(name, domain=None, timeout=5.0):
        return {"candidates": [{"name": "Shopify", "domain": "shopify.com", "logo": None}]}

    monkeypatch.setattr("src.orchestrator.enrich_company", fake_enrich_company)

    result = run_pipeline({"name": "Shopify", "domain": "shopify.com"})

    assert result.status == Status.ACCEPTED
    assert result.conflicts == []
    assert result.confidence_score >= 0.6
    assert result.history[-1]["to_state"] == "accepted"
