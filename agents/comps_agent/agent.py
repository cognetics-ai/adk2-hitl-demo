from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from google.adk import Agent
from google.adk import Event
from google.adk import Workflow
from google.adk import Context
from google.adk.events import RequestInput
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset

from agents import _logger
from agents.research_payload import build_research_payload
from schemas.clients.client import Client

from .schemas import CompsCompanyRecord
from .schemas import PeerCandidate
from .schemas import PeerProposal
from .schemas import PeerReviewDecision
from .sec_workbook import build_sec_comps_records
from .sec_workbook import create_comps_workbook


RESEARCH_MODEL = os.getenv("ADK_RESEARCH_MODEL", "gemini-2.5-flash")
COMPS_ANALYSIS_SKILL = load_skill_from_dir(
    Path(__file__).resolve().parent / "skills" / "comps-analysis"
)
COMPS_ANALYSIS_TOOLSET = skill_toolset.SkillToolset(skills=[COMPS_ANALYSIS_SKILL])


def _payload_from_input(node_input: Any) -> dict[str, Any]:
    return build_research_payload(node_input)


def _state_set(ctx: Context, key: str, value: Any) -> None:
    if hasattr(value, "model_dump"):
        ctx.state[key] = value.model_dump(mode="json")
    elif isinstance(value, list):
        ctx.state[key] = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    else:
        ctx.state[key] = value


def _coerce_peer_proposal(value: Any, state_value: Any | None = None) -> PeerProposal:
    candidate = value
    if isinstance(value, Event):
        candidate = value.output
        if candidate is None and value.content and value.content.parts:
            text_parts = [
                part.text for part in value.content.parts if part.text and not part.thought
            ]
            candidate = "".join(text_parts).strip() if text_parts else None
    if candidate is None:
        candidate = state_value
    if isinstance(candidate, PeerProposal):
        return candidate
    if isinstance(candidate, dict):
        return PeerProposal.model_validate(candidate)
    if isinstance(candidate, str):
        return PeerProposal.model_validate(_parse_peer_proposal_json(candidate))
    if isinstance(state_value, dict):
        return PeerProposal.model_validate(state_value)
    if isinstance(state_value, str):
        return PeerProposal.model_validate(_parse_peer_proposal_json(state_value))
    raise ValueError("Peer selection agent did not return a structured peer proposal.")


def _parse_peer_proposal_json(value: str) -> dict[str, Any]:
    cleaned = value.strip()
    fence_match = re.fullmatch(
        r"```(?:json)?\s*\n(?P<body>.*?)\n```",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fence_match:
        cleaned = fence_match.group("body").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        object_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not object_match:
            raise
        parsed = json.loads(object_match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Peer proposal response must be a JSON object.")
    return parsed


async def set_client_details(ctx: Context, node_input: Any):
    """Resolve target metadata before ADK skill-driven peer selection."""
    payload = _payload_from_input(node_input)
    company = str(
        payload.get("company")
        or payload.get("ticker")
        or payload.get("client_name")
        or payload.get("title")
        or ""
    ).strip()
    if not company:
        raise ValueError("Company or ticker is required for comparables research.")

    title = str(
        payload.get("title")
        or payload.get("company_title")
        or payload.get("client_name")
        or company
    ).strip()
    ticker = str(payload.get("ticker") or "").strip()

    yield Event(message=f"Preparing peer proposal for {title}.")
    _state_set(ctx, "research_request", payload)
    _state_set(ctx, "company", company)
    _state_set(ctx, "title", title)
    _state_set(ctx, "client_name", title)
    _state_set(ctx, "ticker", ticker)
    _state_set(ctx, "scenario_name", payload.get("scenario_name", "Base Case"))
    await asyncio.sleep(0)

    client = Client(
        parent_client_id=payload.get("parent_client_id"),
        parent_client_name=payload.get("parent_client_name") or title,
        client_name=title,
        client_id=payload.get("client_id") or ticker or company,
    )
    _state_set(ctx, "client", client)
    yield Event(
        message=f"Resolved {client.client_name} for comps-analysis skill workflow.",
        output={
            "client": client.model_dump(mode="json"),
            "research_request": payload,
            "title": title,
            "ticker": ticker or None,
            "agent": "comps_agent",
        },
    )


peer_selection_agent = Agent(
    name="peer_selection_agent",
    model=RESEARCH_MODEL,
    instruction="""
You are an investment banking comparable-company peer selection agent.

Use the available ADK skill named `comps-analysis` for this task. Load it
with the ADK skill tools before selecting peers, then follow its workflow.

Target:
- Company: {title}
- Ticker: {ticker}
- Scenario: {scenario_name}

Task:
Return the best public comparable peer proposal for the target. You may use
company names or ticker symbols, but tickers are preferred when known.

Rules:
- Return only one JSON object. Do not wrap it in markdown.
- The JSON object must contain: target_company, target_ticker, as_of_date,
  selection_methodology, suggested_peers, excluded_peers, and data_limitations.
- Each peer object must contain: company_name, ticker, exchange, country,
  peer_category, rationale, and key_differences.
- `peer_category` must be exactly one of: core, secondary, broader_reference.
- `data_limitations` must always be an array of strings, even when there is
  only one limitation.
- Suggest 4-8 peers unless the sector has fewer clean public comps.
- Classify each as core, secondary, or broader_reference.
- Include rationale and key differences for each peer.
- Include excluded peers when likely-but-wrong comps should be called out.
- Do not collect financial statement data and do not produce Excel.
- Do not invent financial metrics.
- The next workflow step must pause for human peer review.
    """,
    tools=[COMPS_ANALYSIS_TOOLSET],
    output_key="peer_proposal",
)


def request_peer_review(ctx: Context, node_input: Any):
    proposal = _coerce_peer_proposal(node_input, ctx.state.get("peer_proposal"))
    _state_set(ctx, "peer_proposal", proposal)
    workflow_request = ctx.state.get("research_request") or {}
    request_id = workflow_request.get("job_id") or proposal.target_ticker or proposal.target_company

    yield RequestInput(
        interrupt_id=f"comps_peer_review:{request_id}",
        message=(
            "Review the proposed comparable-company peer set. Add, remove, or edit "
            "companies before SEC/XBRL data collection and Excel generation begins."
        ),
        payload={
            "proposal": proposal.model_dump(mode="json"),
            "required_controls": [
                "The reviewed peer set becomes the authoritative set.",
                "Deleted peers must not be reintroduced without user approval.",
                "Financial data collection is blocked until this step is approved.",
                "SEC/XBRL values must be left blank when unavailable; no simulated data.",
            ],
        },
        response_schema=PeerReviewDecision,
    )


def _markdown_summary(
    *,
    proposal: PeerProposal,
    review: PeerReviewDecision,
    records: list[CompsCompanyRecord],
    artifact: dict[str, Any],
) -> str:
    successful = [record for record in records if record.status in {"success", "partial"}]
    failed = [record for record in records if record.status not in {"success", "partial"}]
    peer_rows = "\n".join(
        f"| {record.company_name} | {record.ticker or '-'} | {record.peer_category} | "
        f"{record.fiscal_year or '-'} | {record.status} |"
        for record in records
    )
    gaps = "\n".join(
        f"- {record.company_name}: {'; '.join(record.limitations[:2])}"
        for record in failed
    )
    if not gaps:
        gaps = "- No unresolved SEC lookup failures. Some market-data fields remain blank because SEC does not provide live share prices."

    return f"""# Comparable Company Analysis

Target: **{proposal.target_company}** ({proposal.target_ticker or "N/A"})

Peer review completed by {review.decided_by_name or review.decided_by or "the user"}. The selected peer set was used as the authoritative list.

| Company | Ticker | Category | Fiscal Year | SEC Status |
|---|---:|---|---:|---|
{peer_rows}

Generated Excel artifact: `{artifact["filename"]}`

SEC/XBRL records collected: {len(successful)} of {len(records)}.

Data limitations:
{gaps}
"""


def build_sec_excel_node(ctx: Context, node_input: PeerReviewDecision) -> Event:
    if not node_input.approved:
        raise ValueError("Peer review was not approved; comparables workflow stopped.")

    proposal = PeerProposal.model_validate(ctx.state["peer_proposal"])
    workflow_request = ctx.state.get("research_request") or {}
    selected_peers = node_input.selected_peers
    records = build_sec_comps_records(
        target_company=proposal.target_company,
        target_ticker=proposal.target_ticker,
        selected_peers=selected_peers,
    )
    artifact = create_comps_workbook(
        workflow_request=workflow_request,
        proposal=proposal,
        review=node_input,
        records=records,
    )
    markdown = _markdown_summary(
        proposal=proposal,
        review=node_input,
        records=records,
        artifact=artifact.model_dump(mode="json"),
    )

    _state_set(ctx, "peer_review", node_input)
    _state_set(ctx, "comps_dataset", records)
    _state_set(ctx, "comps_excel_artifact", artifact)
    _state_set(ctx, "comparables_markdown", markdown)
    return Event(
        message=f"Generated peer-reviewed SEC/XBRL comps workbook {artifact.filename}.",
        output={
            "comparables_markdown": markdown,
            "comps_excel_artifact": artifact.model_dump(mode="json"),
            "record_count": len(records),
        },
    )


# Backward-compatible name for code/tests that refer to the old final agent.
comm_agent = peer_selection_agent


root_agent = Workflow(
    name="comps_research_workflow",
    edges=[
        (
            "START",
            set_client_details,
            peer_selection_agent,
            request_peer_review,
            build_sec_excel_node,
        ),
    ],
)
