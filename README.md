# M&A DCF Valuation ADK Demo

This repo now includes a front-to-back Google ADK 2.0 Beta workflow that wraps
the DCF notebook into banker-reviewable services:

- deterministic multi-phase DCF valuation math in `valuation/`
- deterministic DCF sensitivity analysis after the point-estimate valuation
- SEC/EDGAR lookup and XBRL normalization in `data/`
- ADK graph workflow with `RequestInput` in `agents/mna_dcf_valuation/`
- ADK research workflow in `agents/company_details_research_agent/`
- ADK comparables workflow in `agents/comps_agent/` with a repo-local
  comps-analysis skill pack, human peer-set review, SEC/XBRL collection, and
  downloadable Excel output
- FastAPI REST endpoints for the React workbench
- React UI for company resolution, source review, assumption collection, DCF
  output, sensitivity tables, Monte Carlo ranges, and ADK event audit

The LLM/agent layer coordinates workflow only. The DCF model is deterministic,
typed, validated, logged, and separated from user-provided assumptions.

## Backend Layout

The backend is organized around ownership boundaries:

- `api/app.py` is the public FastAPI entrypoint for the workbench.
- `api/research_services.py` coordinates the sibling research agents.
- `api/runtime_utils.py` holds shared ADK session and event helpers.
- `api/runtimes/` contains app-facing runtime wrappers for ADK agents.
- `agents/<agent_name>/agent.py` defines an ADK agent or workflow.
- `agents/<agent_name>/__init__.py` exports the ADK `root_agent`.

## Run It

Backend:

```bash
.venv/bin/uvicorn api.app:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

If the backend is not on port `8000`:

```bash
VITE_API_BASE=http://127.0.0.1:8001 npm run dev
```

## Data Modes

- `Notebook sample` uses the Chipotle assumptions from the source notebook and
  runs fully offline.
- `Live SEC` uses SEC company ticker lookup and XBRL companyfacts. Set a firm
  contact user agent before live SEC calls:

```bash
export SEC_USER_AGENT='Your Firm Name valuation-platform@example.com'
```

## Research Agents

The company background and comparables tabs invoke the ADK workflows in
`agents/company_details_research_agent/` and `agents/comps_agent/` through
FastAPI async jobs. These agents use Gemini and Google Search, so set a Google
AI API key before running live research:

```bash
export GOOGLE_API_KEY='<your-api-key>'
export ADK_RESEARCH_MODEL='gemini-2.5-flash'
```

Without `GOOGLE_API_KEY`, the research jobs will be created and routed through
ADK, but they will fail with the model provider's missing API key error.

## ADK Session Store

By default, the runtime uses ADK `DatabaseSessionService` with local SQLite so
the React workbench can be tested immediately:

```text
sqlite+aiosqlite:///api/.adk/session.db
```

For a production-like Postgres session store, set:

```text
postgresql+asyncpg://adk_demo:adk_demo@127.0.0.1:5432/adk_demo_db
schema: adk_store
```

```bash
export ADK_WORKBENCH_DATABASE_URL='postgresql+asyncpg://adk_demo:<password>@127.0.0.1:5432/adk_demo_db'
export ADK_WORKBENCH_DB_SCHEMA='adk_store'
```

The older `ADK_DCF_DATABASE_URL` and `ADK_DCF_DB_SCHEMA` names are still
accepted for compatibility.

Tests use `InMemorySessionService`.

## Tests

```bash
.venv/bin/python -m unittest tests.test_mna_dcf_valuation tests.test_research_payload tests.test_vacation_approval
npm --prefix frontend run build
```

## Key Files

- `valuation/dcf_model.py`: refactored notebook DCF math.
- `valuation/dcf_tool.py`: validated JSON-friendly DCF tool wrapper.
- `valuation/sensitivity.py`: one-factor and two-way DCF sensitivity engine.
- `valuation/monte_carlo.py`: approved-distribution Monte Carlo runner.
- `data/sec_tools.py`: SEC JSON API client with fair-access rate limiting.
- `data/sec_normalizer.py`: conservative XBRL-to-DCF snapshot normalization.
- `api/app.py`: FastAPI app entrypoint that composes the DCF and research
  workflows for the React frontend.
- `api/research_services.py`: async ADK runtime wrapper for company
  background and comparables research.
- `api/runtime_utils.py`: shared ADK session and event serialization helpers.
- `api/runtimes/mna_dcf_valuation.py`: app-facing runtime, session
  materialization, resume payloads, Monte Carlo persistence.
- `agents/mna_dcf_valuation/agent.py`: ADK workflow graph and `RequestInput`.
- `agents/comps_agent/skills/comps-analysis/SKILL.md`: ADK filesystem skill
  loaded through `SkillToolset` by the comps agent.
- `agents/comps_agent/sec_workbook.py`: deterministic SEC/XBRL comps extraction
  and Excel workbook generation.
- `frontend/src/App.jsx`: banker workbench UI.
