"""Guardrail logic: confidence scoring, conflict detection, and routing.

This is the file that decides whether an enriched record can be trusted.
It never blindly accepts enrichment data -- it explicitly checks for three
concrete conflict scenarios and a confidence threshold before routing:

  A. domain_mismatch   -- the input's own domain disagrees with the domain
                           the enrichment source returned for the best-name
                           match.
  B. ambiguous_match    -- two or more enrichment candidates are near-equally
                           good name matches but point at different domains,
                           so picking the top one would be a guess.
  C. raw_notes_conflict -- free-text notes on the record mention a domain
                           that contradicts the enriched domain.

Routing:
  - enrichment service failure (timeout/http/invalid response) -> needs_review
    (the service being unavailable isn't evidence the lead is bad -- a human
    should check rather than auto-rejecting a possibly-good lead)
  - enrichment succeeded but returned zero candidates -> rejected
    (there's nothing to enrich with; total failure)
  - any conflict detected -> needs_review
  - low confidence (no strong name match) -> needs_review
  - high confidence + no conflicts -> accepted
"""

from __future__ import annotations

import difflib
import re

from src.state import LeadState, Status

CONFIDENCE_ACCEPT_THRESHOLD = 0.6
AMBIGUITY_SIMILARITY_GAP = 0.1

_DOMAIN_PATTERN = re.compile(r"\b[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,}\b")


def _normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def _name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def validate(state: LeadState) -> LeadState:
    source_data = state.source_data

    if "error" in source_data:
        state.transition(
            Status.NEEDS_REVIEW, f"enrichment_service_error:{source_data['error']}"
        )
        return state

    candidates = source_data.get("candidates", [])
    if not candidates:
        state.transition(Status.REJECTED, "no_enrichment_data_found")
        return state

    scored = sorted(
        ((c, _name_similarity(state.name, c["name"])) for c in candidates),
        key=lambda pair: pair[1],
        reverse=True,
    )
    top_candidate, top_score = scored[0]
    state.confidence_score = round(top_score, 4)
    enriched_domain = _normalize_domain(top_candidate["domain"])

    conflicts: list[str] = []

    # Scenario A: the input's own domain disagrees with the enriched domain.
    if state.domain:
        input_domain = _normalize_domain(state.domain)
        if input_domain != enriched_domain:
            conflicts.append(
                f"domain_mismatch: input='{input_domain}' vs enriched='{enriched_domain}'"
            )

    # Scenario B: top two candidates are near-tied on name match but disagree on domain.
    if len(scored) >= 2:
        second_candidate, second_score = scored[1]
        second_domain = _normalize_domain(second_candidate["domain"])
        if enriched_domain != second_domain and (top_score - second_score) < AMBIGUITY_SIMILARITY_GAP:
            conflicts.append(
                f"ambiguous_match: '{top_candidate['name']}' ({enriched_domain}) and "
                f"'{second_candidate['name']}' ({second_domain}) are both plausible matches"
            )

    # Scenario C: free-text notes mention a domain that contradicts the enriched one.
    if state.raw_notes:
        mentioned_domains = {
            _normalize_domain(m) for m in _DOMAIN_PATTERN.findall(state.raw_notes)
        }
        contradicting = sorted(d for d in mentioned_domains if d != enriched_domain)
        if contradicting:
            conflicts.append(
                f"raw_notes_conflict: notes mention {contradicting} which does not "
                f"match enriched domain '{enriched_domain}'"
            )

    state.conflicts = conflicts

    if conflicts:
        state.transition(Status.NEEDS_REVIEW, f"conflicts_detected: {'; '.join(conflicts)}")
    elif top_score < CONFIDENCE_ACCEPT_THRESHOLD:
        state.transition(Status.NEEDS_REVIEW, f"low_confidence:{state.confidence_score}")
    else:
        state.transition(Status.ACCEPTED, f"high_confidence_no_conflicts:{state.confidence_score}")

    return state
