"""External retrieval for company enrichment.

This is a REAL, keyless external API call -- not a stub. It hits Clearbit's
public Autocomplete endpoint (https://autocomplete.clearbit.com/v1/companies/suggest),
which was built for lightweight name->company autocomplete widgets and needs no
API key. It returns a list of {name, domain, logo} candidates for a query string.

Because it's an unauthenticated, best-effort public endpoint (not a paid,
SLA-backed API), it can rate-limit, time out, or change shape without notice.
Every response is therefore treated as untrusted: this function never raises --
timeouts, non-200 responses, connection failures, and malformed/empty bodies
are all normalized into a consistent result dict so the orchestrator can route
them into a defined state instead of crashing.
"""

from __future__ import annotations

import httpx

CLEARBIT_AUTOCOMPLETE_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"


def enrich_company(name: str, domain: str | None = None, timeout: float = 5.0) -> dict:
    """Look up a company by name via Clearbit Autocomplete.

    Returns one of:
        {"candidates": [{"name": ..., "domain": ..., "logo": ...}, ...]}
        {"error": "timeout" | "connection_error" | "http_error:<code>" | "invalid_response", "detail": "..."}
    """
    try:
        response = httpx.get(
            CLEARBIT_AUTOCOMPLETE_URL,
            params={"query": name},
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        return {"error": "timeout", "detail": str(exc)}
    except httpx.RequestError as exc:
        return {"error": "connection_error", "detail": str(exc)}

    if response.status_code != 200:
        return {
            "error": f"http_error:{response.status_code}",
            "detail": response.text[:200],
        }

    try:
        payload = response.json()
    except ValueError as exc:
        return {"error": "invalid_response", "detail": f"non-JSON body: {exc}"}

    if not isinstance(payload, list):
        return {"error": "invalid_response", "detail": f"expected a list, got {type(payload).__name__}"}

    candidates = [
        item
        for item in payload
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("domain"), str)
    ]

    return {"candidates": candidates}
