"""LangGraph control flow for the lead enrichment pipeline.

Graph shape:

    START -> enrich -> validate -> [route] -> accepted   -> END
                                            -> needs_review -> END
                                            -> rejected    -> END

`enrich` calls the real Clearbit Autocomplete lookup (src/tools/enrichment.py).
`validate` runs the guardrail checks (src/guardrails/validator.py), which
sets the final status that the conditional edge below routes on.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from src.state import LeadState, Status
from src.tools.enrichment import enrich_company
from src.guardrails.validator import validate
from src.logging_config import get_logger, log_transition

logger = get_logger("lead_enrichment.orchestrator")


def enrich_node(state: LeadState) -> LeadState:
    result = enrich_company(state.name, state.domain)
    state.source_data = result
    if "error" in result:
        state.transition(Status.ENRICHING, f"enrichment call failed: {result['error']}")
    else:
        state.transition(
            Status.ENRICHING,
            f"enrichment call returned {len(result.get('candidates', []))} candidate(s)",
        )
    log_transition(logger, state)
    return state


def validate_node(state: LeadState) -> LeadState:
    state.transition(Status.VALIDATING, "running guardrail checks")
    log_transition(logger, state)
    state = validate(state)
    log_transition(logger, state)
    return state


def _finalize(state: LeadState) -> LeadState:
    logger.info(
        "pipeline_finished",
        extra={
            "record_id": state.record_id,
            "status": state.status.value,
            "confidence_score": state.confidence_score,
            "conflicts": state.conflicts,
        },
    )
    return state


def accepted_node(state: LeadState) -> LeadState:
    return _finalize(state)


def needs_review_node(state: LeadState) -> LeadState:
    return _finalize(state)


def rejected_node(state: LeadState) -> LeadState:
    return _finalize(state)


def route_after_validation(state: LeadState) -> str:
    """Conditional edge: dispatch to the terminal node matching state.status."""
    return {
        Status.ACCEPTED: "accepted",
        Status.NEEDS_REVIEW: "needs_review",
        Status.REJECTED: "rejected",
    }[state.status]


def build_graph():
    graph = StateGraph(LeadState)

    graph.add_node("enrich", enrich_node)
    graph.add_node("validate", validate_node)
    graph.add_node("accepted", accepted_node)
    graph.add_node("needs_review", needs_review_node)
    graph.add_node("rejected", rejected_node)

    graph.add_edge(START, "enrich")
    graph.add_edge("enrich", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "accepted": "accepted",
            "needs_review": "needs_review",
            "rejected": "rejected",
        },
    )
    graph.add_edge("accepted", END)
    graph.add_edge("needs_review", END)
    graph.add_edge("rejected", END)

    return graph.compile()


_compiled_graph = None


def run_pipeline(raw_record: dict) -> LeadState:
    """Run a raw {name, domain?, raw_notes?} record through the full pipeline."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()

    initial_state = LeadState(**raw_record)
    result = _compiled_graph.invoke(initial_state)
    return LeadState(**result)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    input_path = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/sample_input.json")
    records = json.loads(input_path.read_text())

    for raw_record in records:
        final_state = run_pipeline(raw_record)
        print(
            f"\n=== {raw_record['name']} -> {final_state.status.value} "
            f"(confidence={final_state.confidence_score}, conflicts={final_state.conflicts}) ===",
            file=sys.stderr,
        )
