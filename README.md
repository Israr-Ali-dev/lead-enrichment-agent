# Lead & Company Data Enrichment Agent

A small, production-style agentic pipeline: it takes a raw company/lead record, enriches it via a
real external lookup, runs the result through an explicit guardrail, and routes it to a defined
terminal state -- `accepted`, `needs_review`, or `rejected` -- instead of blindly trusting whatever
comes back. Built to demonstrate real orchestration, state handling, guardrails, tests, and
structured logging, not a thin wrapper around an LLM call.

## What it does

Input is a raw record: `{name, domain?, raw_notes?}`. It flows through a LangGraph state machine:

```
received -> enriching -> validating -> accepted
                                     -> needs_review
                                     -> rejected
```

- **enrich** (`src/tools/enrichment.py`) looks the company up via an external API.
- **validate** (`src/guardrails/validator.py`) scores confidence, detects conflicts between the
  input and the enrichment result, and decides the route.
- Every transition -- and every guardrail decision, since a decision here always produces a
  transition with an explanatory reason -- is logged as one JSON line
  (`src/logging_config.py`), so any record's full journey can be reconstructed by grepping stdout
  for its `record_id`.

Run it against the bundled examples:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.orchestrator examples/sample_input.json
```

Run the tests:

```bash
pytest -v
```

## What's real vs. stubbed

**Nothing here is a mock.** `src/tools/enrichment.py` calls the real, public Clearbit Autocomplete
endpoint (`https://autocomplete.clearbit.com/v1/companies/suggest`), which needs no API key and
returns actual `{name, domain, logo}` company candidates. It's used because it's a genuine external
data source that doesn't require signing up for a paid API just to demonstrate this pipeline.

Honest caveat: this is an unauthenticated, best-effort public endpoint originally built for
autocomplete widgets, not a paid SLA-backed API -- it can rate-limit, degrade, or change shape
without notice. That's exactly why `enrichment.py` treats every response as untrusted and never
lets a timeout, non-200 status, connection error, or malformed body crash the pipeline; each is
normalized into a `{"error": ..., "detail": ...}` result that the guardrail routes explicitly
(see `test_api_failure.py`). If you want a production-grade replacement, swap the URL/parsing in
`enrich_company()` for a paid provider (Clearbit's authenticated Company API, Hunter.io, etc.) --
the rest of the pipeline (state machine, guardrail, logging) doesn't need to change.

## The main failure mode this was designed against: conflicting data

The riskiest failure mode for an enrichment agent isn't a missing API key or a timeout -- those are
easy to detect and route away. It's **enrichment data that looks fine but silently disagrees with
what you already know about the lead**: the record says one domain, the external source suggests
another; the record's own free-text notes mention a different domain than what enrichment found; or
the "best match" is ambiguous because two candidates are an equally good name match. Blindly
accepting the enrichment result in any of these cases means silently overwriting good data with
wrong data, or attaching a plausible-looking but incorrect domain to a lead.

`src/guardrails/validator.py` checks for exactly these three scenarios explicitly (not just
"if confidence < X, reject"):

1. `domain_mismatch` -- the input's own domain disagrees with the enriched domain.
2. `ambiguous_match` -- two or more candidates are near-tied on name similarity but point at
   different domains, so picking the top one would be a guess.
3. `raw_notes_conflict` -- free-text notes mention a domain that contradicts the enriched one.

Any conflict routes the record to `needs_review` rather than `accepted` or a hard `rejected` --
the data isn't necessarily wrong, but it isn't safe to trust automatically either. This is verified
by `tests/test_conflicting_data.py`, which feeds in a record with a deliberately mismatched domain,
asserts it ends in `needs_review`, and asserts the specific `domain_mismatch` conflict string
appears both on the returned state and in the structured log trace -- not just that *some* rejection
happened, but that the *right, explainable* reason was recorded.

## Project layout

```
src/
├── orchestrator.py       # LangGraph graph definition / control flow
├── state.py               # LeadState pydantic model + Status enum
├── tools/enrichment.py    # Real external API call (Clearbit Autocomplete)
├── guardrails/validator.py # Conflict detection, confidence scoring, routing
└── logging_config.py      # Structured JSON logger
tests/                      # pytest suite (happy path, conflicts, API failure)
examples/sample_input.json  # Clean, incomplete, contradictory, and garbage sample records
```
