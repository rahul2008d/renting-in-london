# Renting in London

Tool-augmented London rental assistant built with Strands Agents, OpenAI, and Streamlit.

## Overview

This app helps shortlist rental listings in London while enforcing hard mandatory constraints in tool logic and agent orchestration.

Mandatory constraints (always enforced in search pipeline):
- Min bedrooms: 2
- Min bathrooms: 2
- Parking required
- Furnished required
- Max rent: GBP 2300 pcm
- Max distance: 5 miles
- Excluded: house share, retirement home, student accommodation

Fixed context:
- Workplace: `22 Bishopsgate, London EC2N 4BQ`
- Scoring mode: `balanced`
- Commute preference: `fastest` (backend-fixed, not user-controlled)
- Search scope: London-wide by default

## Tech Stack

- Python `>=3.11`
- `uv` package/dependency workflow
- `streamlit`
- `strands-agents[openai]`
- `strands-agents-tools`
- `httpx`
- `python-dotenv`
- `pydantic`

## Current Architecture

Core runtime layers:
1. UI + response validation: `app.py`
2. Agent wiring + prompt contract: `agent.py`
3. Tool implementations: `tools/*.py`
4. Static area/profile data: `data/*.py`

Notes:
- The app uses an agent-only orchestration path.
- Legacy deterministic utility modules were removed.

## Repository Structure

```text
renting-in-london/
|- app.py
|- agent.py
|- README.md
|- pyproject.toml
|- uv.lock
|- data/
|  |- london_areas.py
|  |- area_profiles.py
|- tools/
|  |- rightmove_search.py
|  |- property_details.py
|  |- commute_time.py
|  |- local_amenities.py
|  |- area_intel.py
|  |- price_scorer.py
|  |- decision_ranker.py
|  |- constraint_impact.py
|- utils/
|  |- __init__.py
```

## Runtime Flow

### 1) App startup

- Streamlit app initializes page and sidebar.
- `create_agent()` is loaded lazily from `agent.py`.
- If setup fails, UI shows dependency/env guidance.

### 2) Prompt handling

- User prompt is wrapped with fixed constraints/context.
- For listing-like prompts, extra output contract instructions are appended.
- Agent is called directly.

### 3) Response normalization and validation

For listing responses, the app:
- normalizes section headings to markdown
- validates per-listing fields with a Pydantic model
- validates tool-backed consistency for critical fields:
  - confidence label consistency
  - sq ft presence in `At a glance` when inferable
  - commute text aligned with preferred commute option
  - EPC consistency with property details
- retries agent call (bounded retries) if required fields/checks fail

### 4) Final rendering formatting

- Listing titles are rendered as readable cards (`#### ...`).
- Heading item counts are injected:
  - `Top picks now (n)`
  - `Good with trade-offs (n)`
  - `Rejected with reasons (n)`
- Key labels are styled for stronger key/value distinction.
- Agent runtime badge is shown next to the title and updated after responses.

## Agent Configuration (`agent.py`)

Model:
- Provider: OpenAI via `OpenAIModel`
- Model ID: `gpt-5`

Registered tools:
- `search_london_rentals` — Always searches ALL London boroughs; returns Top Picks + With Trade-offs
- `get_property_details`
- `calculate_commute`
- `analyze_constraint_impact`
- `rank_property_decisions`
- `find_nearby_amenities`
- `get_area_profile`
- `score_properties`

System prompt includes:
- non-negotiable constraints
- London-wide execution expectations
- explicit tool-call contract
- output schema requirements
- diagnostics protocol

## Tool Reference

### `tools/rightmove_search.py`
- `search_london_rentals`: Always searches ALL London boroughs. No area parameter — lists properties from anywhere in London. Uses expanded radius (7 mi) and price (£2500). Returns Top Picks (strict) + With Trade-offs (single minor deviation).

### `tools/property_details.py`
- Pulls full detail payload from Rightmove property page model.
- Includes stations, lettings, contact, EPC, summary fields.

### `tools/commute_time.py`
- Commute provider chain:
  1. SerpApi Google Maps
  2. Google Directions API
  3. TfL fallback
- Returns ranked commute options with durations/changes/lines/walk.

### `tools/local_amenities.py`
- Queries Overpass for:
  - indian grocery
  - restaurant
  - fish shop
  - supermarket
- Supports `amenity_type=all` summary output.

### `tools/area_intel.py`
- Returns curated area profile data with fallback suggestions.

### `tools/price_scorer.py`
- Multi-factor weighted scoring (`balanced`, `budget`, `commute`, `space`, `amenities`).

### `tools/decision_ranker.py`
- Classifies into `Strong Match`, `Maybe`, `Reject` with rationale.

### `tools/constraint_impact.py`
- Explains which single rule is reducing supply most.

## UI Behavior

Current UI includes:
- dark themed chat interface
- sidebar with fixed constraints/context
- auto starter search on first load
- manual `Run starter search` button
- route caption + runtime badge

Removed from UI:
- preferred-area selector
- commute preference selector
- compare-two-properties expander

## Environment Variables

Required:
- `OPENAI_API_KEY`

Optional (commute quality):
- `SERPAPI_KEY` or `SERP_API_KEY`
- `GOOGLE_MAPS_API_KEY`

If optional keys are missing, commute still works through TfL fallback.

## Local Run

Install dependencies:

```bash
uv sync
```

Set env:

```bash
OPENAI_API_KEY=your_key_here
```

Run app:

```bash
uv run streamlit run app.py
```

## Error Handling Strategy

- Tool-level HTTP/JSON errors return structured JSON payloads.
- App catches runtime exceptions and returns user-friendly fallback text.
- Validation/retry loop improves output completeness for listing responses.

## Known Constraints

- Third-party endpoint shape/rate limits can change (Rightmove/Overpass/TfL/Google).
- Inventory can be sparse with strict mandatory rules.
- Some enrichments depend on upstream data quality and available coordinates.

## Development Notes

- Keep tool entrypoints decorated with `@tool`.
- Return JSON strings from tool functions.
- Keep explicit type hints and clear Args/Returns docstrings.
- Prefer non-breaking, incremental changes in `app.py` validation/rendering flow.
