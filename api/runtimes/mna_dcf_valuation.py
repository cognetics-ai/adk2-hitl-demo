from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import date
from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from google.adk import Event
from google.adk.events.event_actions import EventActions
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types
from pydantic import BaseModel
from pydantic import Field

from agents import _logger
from agents.mna_dcf_valuation.agent import BANKERS
from agents.mna_dcf_valuation.agent import DCFWorkflowInput
from agents.mna_dcf_valuation.agent import root_agent
from api.runtime_utils import build_session_service as _build_session_service
from api.runtime_utils import event_to_record as _event_to_record
from api.runtime_utils import is_mapping as _is_mapping
from api.runtime_utils import iso_from_timestamp as _iso_from_timestamp
from api.runtime_utils import utc_now_iso as _now
from data.sample_data import build_sample_financial_snapshot
from data.sample_data import default_dcf_assumptions
from data.sample_data import default_monte_carlo_distributions
from valuation.monte_carlo import run_monte_carlo_valuation
from valuation.schemas import DCFUserAssumptions
from valuation.schemas import DistributionSpec
from valuation.schemas import MonteCarloRunRecord


APP_NAME = "mna_dcf_valuation_demo"
REQUEST_INPUT_FUNCTION_NAME = "adk_request_input"


class CreateDcfWorkflowRequest(BaseModel):
    actor_id: str = "sarah.lee"
    company: str = Field(default="CMG", min_length=1)
    scenario_name: str = Field(default="Base Case", min_length=2, max_length=80)
    valuation_date: date = Field(default_factory=date.today)
    data_source: str = Field(default="sample", pattern="^(sample|sec)$")


class SubmitDcfAssumptionsRequest(BaseModel):
    actor_id: str
    assumptions: DCFUserAssumptions


class RunMonteCarloRequest(BaseModel):
    actor_id: str
    sample_size: int = Field(default=500, ge=10, le=5000)
    seed: int = 42
    distributions: list[DistributionSpec] = Field(min_length=1)
    approval_comment: str | None = None


class DcfWorkflowRecord(BaseModel):
    request_id: str
    session_id: str
    session_user_id: str
    actor_id: str
    company: str | None = None
    ticker: str | None = None
    scenario_name: str | None = None
    status: str
    workflow_request: dict[str, Any] | None = None
    company_record: dict[str, Any] | None = None
    financial_snapshot: dict[str, Any] | None = None
    pending_input: dict[str, Any] | None = None
    assumptions: dict[str, Any] | None = None
    dcf_params: dict[str, Any] | None = None
    valuation_result: dict[str, Any] | None = None
    sensitivity_result: dict[str, Any] | None = None
    valuation_explanation: dict[str, Any] | None = None
    assumption_lineage: dict[str, Any] | None = None
    resume_payloads: list[dict[str, Any]] = Field(default_factory=list)
    monte_carlo_runs: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str


def build_session_service() -> BaseSessionService:
    return _build_session_service(
        database_url_envs=(
            "ADK_DCF_DATABASE_URL",
            "ADK_WORKBENCH_DATABASE_URL",
            "ADK_DEMO_DATABASE_URL",
            "DATABASE_URL",
        ),
        schema_envs=(
            "ADK_DCF_DB_SCHEMA",
            "ADK_WORKBENCH_DB_SCHEMA",
            "ADK_DEMO_DB_SCHEMA",
        ),
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


def _build_user_content(payload: dict[str, Any]) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part(text=json.dumps(payload, default=str))],
    )


def _build_resume_content(
    interrupt_id: str,
    assumptions: DCFUserAssumptions,
) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=REQUEST_INPUT_FUNCTION_NAME,
                    response=assumptions.model_dump(mode="json", exclude_none=True),
                )
            )
        ],
    )


def _record_value(session_state: dict[str, Any], key: str) -> Any:
    return jsonable_encoder(session_state.get(key)) if _is_mapping(session_state) else None


class DcfValuationRuntime:
    def __init__(
        self,
        session_service_factory: Callable[[], BaseSessionService] | None = None,
    ) -> None:
        _logger.debug("Creating M&A DCF runtime")
        self._session_service_factory = session_service_factory or build_session_service
        self.session_service = self._session_service_factory()
        self.runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self.session_service,
            auto_create_session=True,
        )

    def people(self) -> list[dict[str, Any]]:
        return [banker.model_dump(mode="json") for banker in BANKERS.values()]

    def bootstrap(self) -> dict[str, Any]:
        snapshot = build_sample_financial_snapshot()
        assumptions = default_dcf_assumptions(snapshot)
        return {
            "people": self.people(),
            "default_actor_id": "sarah.lee",
            "sample_company": "CMG",
            "sample_snapshot": snapshot.model_dump(mode="json"),
            "sample_assumptions": assumptions.model_dump(mode="json"),
            "sample_distributions": [
                spec.model_dump(mode="json")
                for spec in default_monte_carlo_distributions(assumptions)
            ],
        }

    def _rebuild_runner(self) -> None:
        self.session_service = self._session_service_factory()
        self.runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self.session_service,
            auto_create_session=True,
        )

    async def _close_session_service(self) -> None:
        close = getattr(self.session_service, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def restart(self) -> None:
        await self._close_session_service()
        self._rebuild_runner()

    async def reset(self) -> None:
        sessions = await self.session_service.list_sessions(app_name=APP_NAME)
        for session in sessions.sessions:
            await self.session_service.delete_session(
                app_name=APP_NAME,
                user_id=session.user_id,
                session_id=session.id,
            )
        await self._close_session_service()
        self._rebuild_runner()

    async def create_workflow(
        self,
        payload: CreateDcfWorkflowRequest,
    ) -> DcfWorkflowRecord:
        if payload.actor_id not in BANKERS:
            raise ValueError("Unknown actor_id.")
        request_id = f"dcf-{uuid4().hex[:8]}"
        workflow_input = DCFWorkflowInput(
            request_id=request_id,
            actor_id=payload.actor_id,
            company=payload.company,
            scenario_name=payload.scenario_name,
            valuation_date=payload.valuation_date,
            data_source=payload.data_source,  # type: ignore[arg-type]
        )
        content = _build_user_content(workflow_input.model_dump(mode="json"))
        return await self._run_workflow(
            session_user_id=payload.actor_id,
            session_id=request_id,
            content=content,
        )

    async def submit_assumptions(
        self,
        request_id: str,
        payload: SubmitDcfAssumptionsRequest,
    ) -> DcfWorkflowRecord:
        if payload.actor_id not in BANKERS:
            raise ValueError("Unknown actor_id.")
        record = await self.get_record(request_id)
        if record.pending_input is None:
            raise ValueError("This valuation is not waiting for assumptions.")
        banker = BANKERS[payload.actor_id]
        assumptions = payload.assumptions.model_copy(
            update={
                "provided_by": banker.id,
                "provided_by_name": banker.name,
            }
        )
        interrupt_id = record.pending_input["interrupt_id"]
        content = _build_resume_content(interrupt_id, assumptions)
        return await self._run_workflow(
            session_user_id=record.session_user_id,
            session_id=record.session_id,
            content=content,
        )

    async def run_monte_carlo(
        self,
        request_id: str,
        payload: RunMonteCarloRequest,
    ) -> DcfWorkflowRecord:
        if payload.actor_id not in BANKERS:
            raise ValueError("Unknown actor_id.")
        record = await self.get_record(request_id)
        if record.dcf_params is None or record.valuation_result is None:
            raise ValueError("Run point-estimate DCF before Monte Carlo.")
        banker = BANKERS[payload.actor_id]
        result = run_monte_carlo_valuation(
            record.dcf_params,
            payload.distributions,
            sample_size=payload.sample_size,
            seed=payload.seed,
        )
        run_record = MonteCarloRunRecord(
            run_id=f"mc-{uuid4().hex[:8]}",
            requested_by=banker.id,
            requested_by_name=banker.name,
            sample_size=payload.sample_size,
            seed=payload.seed,
            distributions=payload.distributions,
            result=result,
            created_at=datetime.now(timezone.utc),
        )

        session = await self.session_service.get_session(
            app_name=APP_NAME,
            user_id=record.session_user_id,
            session_id=record.session_id,
        )
        if session is None:
            raise KeyError("Unknown request_id.")
        existing = list(session.state.get("monte_carlo_runs", []))
        existing.append(run_record.model_dump(mode="json"))
        event = Event(
            author="api",
            message=f"Monte Carlo run {run_record.run_id} completed.",
            output=run_record.model_dump(mode="json"),
            actions=EventActions(state_delta={"monte_carlo_runs": existing}),
        )
        await self.session_service.append_event(session, event)
        return await self.get_record(request_id)

    async def visible_records(self, actor_id: str) -> list[DcfWorkflowRecord]:
        if actor_id not in BANKERS:
            raise ValueError("Unknown actor_id.")
        records = await self._materialize_all_records()
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    async def get_record(self, request_id: str) -> DcfWorkflowRecord:
        session_refs = await self.session_service.list_sessions(app_name=APP_NAME)
        matches = [session for session in session_refs.sessions if session.id == request_id]
        if not matches:
            raise KeyError("Unknown request_id.")
        session_ref = matches[0]
        session = await self.session_service.get_session(
            app_name=APP_NAME,
            user_id=session_ref.user_id,
            session_id=session_ref.id,
        )
        if session is None:
            raise KeyError("Unknown request_id.")
        return self._materialize_record(session)

    async def _materialize_all_records(self) -> list[DcfWorkflowRecord]:
        response = await self.session_service.list_sessions(app_name=APP_NAME)
        records: list[DcfWorkflowRecord] = []
        for session_ref in response.sessions:
            session = await self.session_service.get_session(
                app_name=APP_NAME,
                user_id=session_ref.user_id,
                session_id=session_ref.id,
            )
            if session is not None:
                records.append(self._materialize_record(session))
        return records

    def _materialize_record(self, session: Any) -> DcfWorkflowRecord:
        events = [_event_to_record(event) for event in session.events]
        state = session.state if _is_mapping(session.state) else {}
        workflow_request = _record_value(state, "workflow_request")
        company_record = _record_value(state, "company")
        financial_snapshot = _record_value(state, "financial_snapshot")
        assumptions = _record_value(state, "assumptions")
        dcf_params = _record_value(state, "dcf_params")
        valuation_result = _record_value(state, "valuation_result")
        sensitivity_result = _record_value(state, "sensitivity_result")
        valuation_explanation = _record_value(state, "valuation_explanation")
        assumption_lineage = _record_value(state, "assumption_lineage")
        monte_carlo_runs = _record_value(state, "monte_carlo_runs") or []

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

        if valuation_result is not None:
            status = "valuation_complete"
        elif pending_input is not None:
            status = "awaiting_assumptions"
        elif financial_snapshot is not None:
            status = "normalized"
        else:
            status = "running"

        created_at = (
            events[0].get("timestamp")
            if events
            else _iso_from_timestamp(session.last_update_time)
        ) or _now()
        updated_at = (
            _iso_from_timestamp(session.last_update_time)
            or (events[-1].get("timestamp") if events else None)
            or created_at
        )

        return DcfWorkflowRecord(
            request_id=(workflow_request or {}).get("request_id", session.id),
            session_id=session.id,
            session_user_id=session.user_id,
            actor_id=(workflow_request or {}).get("actor_id", session.user_id),
            company=(workflow_request or {}).get("company"),
            ticker=(company_record or financial_snapshot or {}).get("ticker"),
            scenario_name=(
                (assumptions or {}).get("scenario_name")
                or (workflow_request or {}).get("scenario_name")
            ),
            status=status,
            workflow_request=workflow_request,
            company_record=company_record,
            financial_snapshot=financial_snapshot,
            pending_input=pending_input,
            assumptions=assumptions,
            dcf_params=dcf_params,
            valuation_result=valuation_result,
            sensitivity_result=sensitivity_result,
            valuation_explanation=valuation_explanation,
            assumption_lineage=assumption_lineage,
            resume_payloads=resume_payloads,
            monte_carlo_runs=monte_carlo_runs,
            events=events,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def _run_workflow(
        self,
        session_user_id: str,
        session_id: str,
        content: types.Content,
    ) -> DcfWorkflowRecord:
        async for event in self.runner.run_async(
            user_id=session_user_id,
            session_id=session_id,
            new_message=content,
        ):
            _logger.debug("DCF workflow event: %s", _event_to_record(event))
        return await self.get_record(session_id)


runtime = DcfValuationRuntime()
