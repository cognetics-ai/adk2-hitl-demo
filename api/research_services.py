from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Literal
from uuid import uuid4

from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types
from pydantic import BaseModel
from pydantic import Field

from agents import _logger
from agents.company_details_research_agent.agent import root_agent as company_details_root_agent
from agents.comps_agent.agent import root_agent as comps_root_agent
from agents.comps_agent.schemas import PeerReviewDecision
from api.runtime_utils import build_session_service
from api.runtime_utils import event_to_record as _event_to_record
from api.runtime_utils import is_mapping as _is_mapping
from data.sample_data import lookup_sample_company
from data.sec_tools import SecClientError
from data.sec_tools import lookup_company


ResearchWorkflowType = Literal["company_background", "comparables"]
ResearchWorkflowStatus = Literal[
    "queued",
    "running",
    "awaiting_peer_review",
    "completed",
    "failed",
]
REQUEST_INPUT_FUNCTION_NAME = "adk_request_input"


class ResearchWorkflowRequest(BaseModel):
    actor_id: str = Field(default="sarah.lee", min_length=1)
    company: str = Field(default="CMG", min_length=1)
    title: str | None = Field(
        default=None,
        description="Resolved full company name to place in ADK state.",
    )
    ticker: str | None = Field(default=None, description="Resolved ticker, if public.")
    scenario_name: str = Field(default="Base Case", min_length=1)
    data_source: Literal["sample", "sec"] = "sample"


class ResearchWorkflowRecord(BaseModel):
    job_id: str
    workflow_type: ResearchWorkflowType
    source_agent: str
    company: str
    title: str | None = None
    ticker: str | None = None
    scenario_name: str
    status: ResearchWorkflowStatus
    markdown: str | None = None
    pending_input: dict[str, Any] | None = None
    resume_payloads: list[dict[str, Any]] = Field(default_factory=list)
    peer_proposal: dict[str, Any] | None = None
    peer_review: dict[str, Any] | None = None
    comps_excel_artifact: dict[str, Any] | None = None
    error: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    adk_app_name: str
    adk_session_id: str
    created_at: str
    updated_at: str


class SubmitCompsPeerReviewRequest(BaseModel):
    actor_id: str = Field(default="sarah.lee", min_length=1)
    approved: bool = True
    selected_peers: list[dict[str, Any]] = Field(min_length=1)
    comment: str | None = None


@dataclass(frozen=True)
class ResearchWorkflowConfig:
    workflow_type: ResearchWorkflowType
    source_agent: str
    final_agent_name: str
    app_name: str
    root_agent: Any
    output_key: str
    job_prefix: str


DEFAULT_RESEARCH_CONFIGS: tuple[ResearchWorkflowConfig, ...] = (
    ResearchWorkflowConfig(
        workflow_type="company_background",
        source_agent="company_details_research_agent",
        final_agent_name="cdr_agent",
        app_name="company_details_research_agent",
        root_agent=company_details_root_agent,
        output_key="company_background_markdown",
        job_prefix="company-bg",
    ),
    ResearchWorkflowConfig(
        workflow_type="comparables",
        source_agent="comps_agent",
        final_agent_name="peer_selection_agent",
        app_name="comps_agent",
        root_agent=comps_root_agent,
        output_key="comparables_markdown",
        job_prefix="comps",
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(message: str) -> dict[str, Any]:
    return {"timestamp": _now(), "message": message}


def _build_user_content(payload: dict[str, Any]) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part(text=json.dumps(payload, default=str))],
    )


def _build_resume_content(
    interrupt_id: str,
    response: BaseModel,
) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=REQUEST_INPUT_FUNCTION_NAME,
                    response=response.model_dump(mode="json", exclude_none=True),
                )
            )
        ],
    )


def _extract_request_input(event_record: dict[str, Any]) -> dict[str, Any] | None:
    function_call = event_record.get("function_call")
    if not function_call or function_call.get("name") != REQUEST_INPUT_FUNCTION_NAME:
        return None
    args = function_call.get("args") or {}
    return {
        "interrupt_id": function_call["id"],
        "function_name": function_call["name"],
        "message": args.get("message"),
        "payload": args.get("payload"),
        "response_schema": args.get("response_schema"),
    }


def _extract_resume_payload(event_record: dict[str, Any]) -> dict[str, Any] | None:
    function_response = event_record.get("function_response")
    if (
        not function_response
        or function_response.get("name") != REQUEST_INPUT_FUNCTION_NAME
    ):
        return None
    return {
        "payload": {
            "role": "user",
            "parts": [{"functionResponse": function_response}],
        },
        "submitted_at": event_record.get("timestamp"),
    }


def _pending_input_from_events(
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    pending_input: dict[str, Any] | None = None
    resolved_interrupt_ids: set[str] = set()
    resume_payloads: list[dict[str, Any]] = []
    for event_record in events:
        request_input = _extract_request_input(event_record)
        if request_input is not None:
            pending_input = request_input
        resume_payload = _extract_resume_payload(event_record)
        if resume_payload is not None:
            resume_payloads.append(resume_payload)
            function_response = event_record["function_response"]
            resolved_interrupt_ids.add(function_response["id"])

    if pending_input and pending_input["interrupt_id"] in resolved_interrupt_ids:
        pending_input = None
    return pending_input, resume_payloads


def _initial_ticker(company: str) -> str | None:
    normalized = company.strip().upper()
    if 1 <= len(normalized) <= 8 and normalized.replace(".", "").replace("-", "").isalnum():
        return normalized
    return None


def _resolve_research_company(payload: ResearchWorkflowRequest) -> dict[str, str | None]:
    submitted_company = payload.company.strip()
    if payload.title:
        return {
            "company": submitted_company,
            "title": payload.title.strip(),
            "ticker": payload.ticker or _initial_ticker(submitted_company),
        }

    if submitted_company.upper() in {"CMG", "CHIPOTLE", "CHIPOTLE MEXICAN GRILL"}:
        company = lookup_sample_company(submitted_company)
        return {
            "company": submitted_company,
            "title": company.title,
            "ticker": company.ticker,
        }

    try:
        result = lookup_company(submitted_company)
    except SecClientError as exc:
        _logger.warning(
            "SEC title resolution failed for %s; using submitted company. Error: %s",
            submitted_company,
            exc,
        )
        return {
            "company": submitted_company,
            "title": submitted_company,
            "ticker": payload.ticker or _initial_ticker(submitted_company),
        }

    if result.get("status") == "success":
        best = result["best_match"]
        return {
            "company": submitted_company,
            "title": best["title"],
            "ticker": best["ticker"],
        }

    return {
        "company": submitted_company,
        "title": submitted_company,
        "ticker": payload.ticker or _initial_ticker(submitted_company),
    }


def _clean_markdown_output(markdown: str) -> str:
    cleaned = markdown.strip()
    fence_match = re.fullmatch(
        r"```(?:markdown|md)?\s*\n(?P<body>.*?)\n```",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fence_match:
        return fence_match.group("body").strip()
    return cleaned


def _coerce_markdown_value(value: Any, *, output_key: str | None = None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, dict):
        return None

    candidate_keys = [
        key
        for key in (
            output_key,
            "markdown",
            "content",
            "text",
            "message",
            "output",
        )
        if key
    ]
    for key in candidate_keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _event_matches_final_agent(
    event: dict[str, Any],
    *,
    final_agent_name: str,
) -> bool:
    if event.get("author") == final_agent_name:
        return True
    node_path = str(event.get("node_path") or "")
    return bool(re.search(rf"(^|/){re.escape(final_agent_name)}@\d+", node_path))


def _latest_state_delta_text(
    events: list[dict[str, Any]],
    *,
    output_key: str,
) -> str | None:
    for event in reversed(events):
        state_delta = event.get("state_delta")
        if not isinstance(state_delta, dict):
            continue
        markdown = _coerce_markdown_value(
            state_delta.get(output_key),
            output_key=output_key,
        )
        if markdown:
            return markdown
    return None


def _latest_event_text(
    events: list[dict[str, Any]],
    *,
    final_agent_name: str,
    output_key: str | None = None,
) -> str | None:
    for event in reversed(events):
        if not _event_matches_final_agent(event, final_agent_name=final_agent_name):
            continue
        for key in ("output", "message"):
            markdown = _coerce_markdown_value(event.get(key), output_key=output_key)
            if markdown:
                return markdown
    return None


def _latest_event_error(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        message = event.get("error_message")
        if not isinstance(message, str) or not message.strip():
            continue
        code = event.get("error_code")
        if isinstance(code, str) and code.strip():
            return f"{code}: {message.strip()}"
        return message.strip()
    return None


def _event_shape_summary(events: list[dict[str, Any]]) -> str:
    summaries: list[str] = []
    for event in events[-5:]:
        author = event.get("author") or "unknown"
        node_path = event.get("node_path") or ""
        has_message = bool(event.get("message"))
        has_output = bool(event.get("output"))
        summaries.append(
            f"{author} node={node_path or '-'} message={has_message} output={has_output}"
        )
    return "; ".join(summaries) if summaries else "no ADK events"


def _display_events(
    events: list[dict[str, Any]],
    *,
    markdown: str,
) -> list[dict[str, Any]]:
    displayable: list[dict[str, Any]] = []
    for event in events:
        message = event.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        cleaned_message = _clean_markdown_output(message)
        if cleaned_message == markdown:
            continue
        if "\n" in message or len(message) > 280:
            continue
        displayable.append(event)
    return displayable


def build_research_session_service() -> BaseSessionService:
    return build_session_service(
        database_url_envs=(
            "ADK_RESEARCH_DATABASE_URL",
            "ADK_WORKBENCH_DATABASE_URL",
            "ADK_DCF_DATABASE_URL",
            "ADK_DEMO_DATABASE_URL",
            "DATABASE_URL",
        ),
        schema_envs=(
            "ADK_RESEARCH_DB_SCHEMA",
            "ADK_WORKBENCH_DB_SCHEMA",
            "ADK_DCF_DB_SCHEMA",
            "ADK_DEMO_DB_SCHEMA",
        ),
    )


class AsyncResearchService:
    """Async ADK runtime wrapper for the company details and comps agents."""

    def __init__(
        self,
        *,
        session_service_factory: Callable[[], BaseSessionService] | None = None,
        configs: tuple[ResearchWorkflowConfig, ...] = DEFAULT_RESEARCH_CONFIGS,
    ) -> None:
        self._session_service_factory = (
            session_service_factory or build_research_session_service
        )
        self._configs = {config.workflow_type: config for config in configs}
        self._jobs: dict[str, ResearchWorkflowRecord] = {}
        self._build_runners()

    def start_company_background(
        self,
        payload: ResearchWorkflowRequest,
    ) -> ResearchWorkflowRecord:
        return self._start(payload=payload, workflow_type="company_background")

    def start_comparables(self, payload: ResearchWorkflowRequest) -> ResearchWorkflowRecord:
        return self._start(payload=payload, workflow_type="comparables")

    def get_job(self, job_id: str) -> ResearchWorkflowRecord:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"Unknown research job {job_id}") from exc

    async def submit_comparable_peers(
        self,
        job_id: str,
        payload: SubmitCompsPeerReviewRequest,
    ) -> ResearchWorkflowRecord:
        job = self.get_job(job_id)
        if job.workflow_type != "comparables":
            raise ValueError("Peer review can only be submitted for comparables jobs.")
        if job.pending_input is None:
            raise ValueError("This comparables workflow is not waiting for peer review.")

        decision = PeerReviewDecision.model_validate(
            {
                "approved": payload.approved,
                "selected_peers": payload.selected_peers,
                "comment": payload.comment,
                "decided_by": payload.actor_id,
                "decided_by_name": payload.actor_id,
            }
        )
        config = self._configs["comparables"]
        content = _build_resume_content(job.pending_input["interrupt_id"], decision)
        return await self._run_agent_job(
            job_id,
            ResearchWorkflowRequest(
                actor_id=payload.actor_id,
                company=job.company,
                title=job.title,
                ticker=job.ticker,
                scenario_name=job.scenario_name,
                data_source="sec",
            ),
            config,
            resume_content=content,
        )

    async def reset(self) -> None:
        self._jobs.clear()
        for config in self._configs.values():
            sessions = await self.session_service.list_sessions(app_name=config.app_name)
            for session in sessions.sessions:
                await self.session_service.delete_session(
                    app_name=config.app_name,
                    user_id=session.user_id,
                    session_id=session.id,
                )
        await self._close_session_service()
        self._build_runners()

    async def restart(self) -> None:
        self._jobs.clear()
        await self._close_session_service()
        self._build_runners()

    def _build_runners(self) -> None:
        self.session_service = self._session_service_factory()
        self._runners = {
            config.workflow_type: Runner(
                app_name=config.app_name,
                agent=config.root_agent,
                session_service=self.session_service,
                auto_create_session=True,
            )
            for config in self._configs.values()
        }

    async def _close_session_service(self) -> None:
        close = getattr(self.session_service, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def _start(
        self,
        *,
        payload: ResearchWorkflowRequest,
        workflow_type: ResearchWorkflowType,
    ) -> ResearchWorkflowRecord:
        _logger.info(
            "Starting research workflow for %s with type %s",
            payload.company,
            workflow_type,
        )
        config = self._configs[workflow_type]
        resolved_company = _resolve_research_company(payload)
        company = resolved_company["company"] or payload.company.strip()
        title = resolved_company["title"] or company
        ticker = resolved_company["ticker"] or _initial_ticker(company)
        timestamp = _now()
        job = ResearchWorkflowRecord(
            job_id=f"{config.job_prefix}-{uuid4().hex[:8]}",
            workflow_type=workflow_type,
            source_agent=config.source_agent,
            company=company,
            title=title,
            ticker=ticker,
            scenario_name=payload.scenario_name,
            status="queued",
            events=[_event("ADK research workflow queued.")],
            adk_app_name=config.app_name,
            adk_session_id="",
            created_at=timestamp,
            updated_at=timestamp,
        )
        job = job.model_copy(update={"adk_session_id": job.job_id})
        self._jobs[job.job_id] = job
        _logger.info(
            "Queued %s ADK research workflow %s for %s",
            workflow_type,
            job.job_id,
            title,
        )
        asyncio.create_task(self._run_agent_job(job.job_id, payload, config))
        return job

    async def _run_agent_job(
        self,
        job_id: str,
        payload: ResearchWorkflowRequest,
        config: ResearchWorkflowConfig,
        resume_content: types.Content | None = None,
    ) -> ResearchWorkflowRecord:
        job = self._jobs[job_id]
        self._jobs[job_id] = job.model_copy(
            update={
                "status": "running",
                "events": [*job.events, _event(f"{config.source_agent} runtime started.")],
                "updated_at": _now(),
            }
        )
        try:
            if resume_content is None:
                request_payload = {
                    **payload.model_dump(mode="json"),
                    "company": job.company,
                    "title": job.title or job.company,
                    "client_name": job.title or job.company,
                    "ticker": job.ticker,
                    "job_id": job_id,
                    "workflow_type": config.workflow_type,
                    "source_agent": config.source_agent,
                }
                content = _build_user_content(request_payload)
            else:
                content = resume_content
            adk_events: list[dict[str, Any]] = []
            async for event in self._runners[config.workflow_type].run_async(
                user_id=payload.actor_id,
                session_id=job_id,
                new_message=content,
            ):
                adk_events.append(_event_to_record(event))

            session = await self.session_service.get_session(
                app_name=config.app_name,
                user_id=payload.actor_id,
                session_id=job_id,
            )
            state = session.state if session is not None and _is_mapping(session.state) else {}
            all_events = (
                [_event_to_record(event) for event in session.events]
                if session is not None
                else adk_events
            )
            pending_input, resume_payloads = _pending_input_from_events(all_events)
            if pending_input is not None:
                job = self._jobs[job_id]
                self._jobs[job_id] = job.model_copy(
                    update={
                        "status": "awaiting_peer_review",
                        "pending_input": pending_input,
                        "resume_payloads": resume_payloads,
                        "peer_proposal": state.get("peer_proposal"),
                        "events": [
                            *job.events,
                            *_display_events(adk_events, markdown=""),
                            _event("comps_agent is waiting for peer review."),
                        ],
                        "updated_at": _now(),
                    }
                )
                _logger.info("Comparables workflow %s is waiting for peer review", job_id)
                return self._jobs[job_id]
            markdown = _coerce_markdown_value(
                state.get(config.output_key),
                output_key=config.output_key,
            ) or _latest_state_delta_text(
                adk_events,
                output_key=config.output_key,
            ) or _latest_event_text(
                adk_events,
                final_agent_name=config.final_agent_name,
                output_key=config.output_key,
            )
            if not isinstance(markdown, str) or not markdown.strip():
                event_error = _latest_event_error(adk_events)
                if event_error:
                    raise RuntimeError(f"{config.source_agent} failed in ADK: {event_error}")
                raise ValueError(
                    f"{config.source_agent} completed without markdown output in "
                    f"state key {config.output_key}. Event summary: "
                    f"{_event_shape_summary(adk_events)}."
                )
            markdown = _clean_markdown_output(markdown)
            display_events = _display_events(adk_events, markdown=markdown)

            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": "completed",
                    "markdown": markdown,
                    "pending_input": None,
                    "resume_payloads": resume_payloads,
                    "peer_proposal": state.get("peer_proposal"),
                    "peer_review": state.get("peer_review"),
                    "comps_excel_artifact": state.get("comps_excel_artifact"),
                    "events": [
                        *job.events,
                        *display_events,
                        _event(f"{config.source_agent} generated markdown output."),
                    ],
                    "updated_at": _now(),
                }
            )
            _logger.info("Completed ADK research workflow %s", job_id)
            return self._jobs[job_id]
        except Exception as exc:
            _logger.exception("ADK research workflow %s failed", job_id)
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": "failed",
                    "error": str(exc),
                    "events": [
                        *job.events,
                        _event(f"{config.source_agent} failed: {exc}"),
                    ],
                    "updated_at": _now(),
                }
            )
            return self._jobs[job_id]


research_service = AsyncResearchService()
