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
    return state


def validate_node(state: LeadState) -> LeadState:
    state.transition(Status.VALIDATING, "running guardrail checks")
    return validate(state)


def accepted_node(state: LeadState) -> LeadState:
    state.transition(Status.ACCEPTED, "reached accepted terminal state")
    return state


def needs_review_node(state: LeadState) -> LeadState:
    state.transition(Status.NEEDS_REVIEW, "reached needs_review terminal state")
    return state


def rejected_node(state: LeadState) -> LeadState:
    state.transition(Status.REJECTED, "reached rejected terminal state")
    return state


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
