# Renting in London

An AI rental assistant for London: it searches live Rightmove listings, scores and ranks them using many real-world signals, and explains trade-offs clearly. You chat in a simple web UI; the assistant handles search breadth, prioritisation, and optional deep dives into commutes, amenities, and neighbourhood context.

---

## What it does

**London-wide discovery** — Every search sweeps across London (not a single borough), so you see a broad pool of listings that match your hard rules.

**Mandatory rules (always applied)** — The pipeline enforces: at least 2 bedrooms and 2 bathrooms, furnished only, rent cap £2,300 pcm, within 5 miles, and it drops house shares, retirement-only, and student-only listings.

**Parking as a real-world signal** — Parking is *preferred*, not a blunt filter. Listings are tagged when parking is clearly there, unclear, or clearly absent, and that feeds both search bucketing and scoring—without throwing away good homes just because the short summary doesn’t mention a bay.

**One ranking brain** — After search, every listing is scored on a wide set of dimensions (value, space, area/zone, commute proxy, local amenity richness, parking, how fresh the listing is, how complete the data is, amenity tags, and **listing quality** derived from the text). Those roll up into a total score and a **recommendation tier** (e.g. highly recommended vs worth viewing vs consider if flexible vs low priority). That scoring step is the single source of truth for ordering and tier labels in the first response—there isn’t a separate “decision” pass in the automatic flow.

**Listing quality from text** — The assistant infers signals from what the listing actually says: heating, light, noise, outdoor space, security, storage, glazing, building age cues, hidden cost hints, EPC hints, and more. That improves fairness when comparing thin vs detailed listings.

**Three-part first answer** — Typical replies are organised into **Top picks now**, **Good with trade-offs**, and **Rejected with reasons** (usually a count), driven by those tiers plus parking confirmation and trade-off reasons—not by a second classifier running before the score.

**Depth on demand** — Ask about a specific home and the assistant can pull full listing details, commute options to a fixed City office (22 Bishopsgate), nearby groceries and eateries, and curated area notes—only when you want that detail, so the first screen stays scannable.

**When results feel thin** — If you ask why supply is low or what’s bottlenecking, the assistant can run a **constraint impact** analysis and summarise what filter is costing you the most listings.

**Optional extra classification** — If you explicitly want properties grouped or re-ranked in a custom way, an on-demand classifier tool is still available; it’s no longer part of the default search-and-reply path.

---

## How the experience is structured

1. **Search & score** — For rental-style questions, the assistant runs a live search and then scores the full result set before writing anything. You get a complete shortlist, not a partial teaser.

2. **Scan the shortlist** — Compact cards summarise price, beds, baths, type, zone, parking status, tags, floor area when known, quality highlights, recommendation tier, trade-offs where relevant, and a Rightmove link.

3. **Go deeper when ready** — Full “detail card” answers (commute lens, stations, EPC, agent contact, maps link, richer summary) appear when you ask for a specific property or a comparison.

4. **Light-touch checks in the app** — The Streamlit app can retry if a *detailed* answer is missing obvious structure (e.g. confidence label, link shape, Google Maps commute link, minimum summary length). It does **not** re-fetch listing or commute APIs just to validate numbers—that keeps the UI responsive; factual accuracy is handled by the agent and tools when they run.

---

## Fixed context (built into the product)

- **Workplace for commute** — 22 Bishopsgate, London EC2N 4BQ  
- **Scoring preset** — Balanced (weights tuned for a mix of price, space, commute, and quality)  
- **Commute preference** — Wired through app context (today: fastest door-to-door; the agent contract also allows least walking / fewest changes if the UI ever exposes them)  
- **Search scope** — London-wide by default  

---

## Capabilities at a glance

| Area | What you get |
|------|----------------|
| **Search** | Live Rightmove rental search with client-side filters aligned to your rules |
| **Scoring & tiers** | Multi-factor score + recommendation tier for every listing in the batch |
| **Details** | Full page payload when you drill in (features, agent, EPC, stations, etc.) |
| **Commute** | Google Maps–style routing via SerpAPI when configured, with TfL fallback |
| **Amenities** | Nearby Indian groceries, restaurants, fishmongers, supermarkets (OpenStreetMap) |
| **Area intel** | Neighbourhood flavour, transport, green space—curated where available |
| **Diagnostics** | “Why so few results?” style analysis on request |
| **Optional rank** | Custom re-ranking / bucket labels only if you ask |

---

## Tech stack (brief)

Python 3.11+, [uv](https://github.com/astral-sh/uv) for dependencies, [Streamlit](https://streamlit.io/) for the UI, [Strands Agents](https://strandsagents.com/) with OpenAI for the assistant, HTTP via `httpx`, and Pydantic for validating structured parts of the reply.

---

## Repository layout

```text
renting-in-london/
├── app.py                 # Streamlit UI, formatting, validation retries
├── agent.py               # System prompt and tool wiring
├── data/                  # London areas, neighbourhood profiles
├── tools/
│   ├── rightmove_search.py
│   ├── property_details.py
│   ├── commute_time.py
│   ├── local_amenities.py
│   ├── area_intel.py
│   ├── price_scorer.py    # Main scoring + tiers (uses listing_signals)
│   ├── listing_signals.py # Text signal extraction (helper, not a separate tool)
│   ├── decision_ranker.py # Optional on-demand classification
│   └── constraint_impact.py
├── pyproject.toml
└── uv.lock
```

---

## Environment variables

**Required**

- `OPENAI_API_KEY` — powers the assistant

**Optional (richer commutes)**

- `SERPAPI_KEY` or `SERP_API_KEY` — Google Maps–style directions when available  
- `GOOGLE_MAPS_API_KEY` — additional routing fallback  

If optional keys are missing, commute still works via TfL fallback where possible.

---

## Local run

```bash
uv sync
```

```bash
export OPENAI_API_KEY=your_key_here
```

```bash
uv run streamlit run app.py
```

The UI uses a dark theme, shows mandatory filters in the sidebar, can auto-run a starter search on first load, and displays how long the agent took for each reply.

---

## Honest limitations

- Listing **summaries** from search are short—parking and perks are inferred from visible text; the assistant flags uncertainty instead of guessing.  
- **Third-party services** (Rightmove, maps, Overpass, TfL) can change behaviour, rate-limit, or return sparse data.  
- **Strict rules** mean fewer listings; that’s intentional, but it can feel quiet in tight markets.  

---

## Development notes

Tools exposed to the agent return JSON strings (framework convention). Helper modules used only for scoring logic are not separate chat tools. Prefer incremental changes to prompts and validation so the chat experience stays stable.
