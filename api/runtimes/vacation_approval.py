from __future__ import annotations

import json
import inspect
from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types
from pydantic import BaseModel
from pydantic import Field

from agents import _logger
from agents.vacation_approval.agent import EMPLOYEES
from agents.vacation_approval.agent import ManagerDecision
from agents.vacation_approval.agent import VacationSubmission
from agents.vacation_approval.agent import root_agent
from api.runtime_utils import build_session_service as _build_session_service
from api.runtime_utils import event_to_record as _event_to_record
from api.runtime_utils import is_mapping as _is_mapping
from api.runtime_utils import iso_from_timestamp as _iso_from_timestamp
from api.runtime_utils import utc_now_iso as _now


APP_NAME = "vacation_approval_demo"
REQUEST_INPUT_FUNCTION_NAME = "adk_request_input"


class CreateVacationRequest(BaseModel):
    actor_id: str
    start_date: date
    end_date: date
    reason: str = Field(min_length=3)


class SubmitManagerDecisionRequest(BaseModel):
    actor_id: str
    approved: bool
    approved_days: int | None = Field(default=None, ge=0)
    comment: str | None = None


class WorkflowRecord(BaseModel):
    request_id: str
    session_id: str
    session_user_id: str
    employee_id: str
    manager_id: str
    status: str
    request: dict[str, Any] | None = None
    pending_input: dict[str, Any] | None = None
    final_decision: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    resume_payloads: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str


def build_session_service() -> BaseSessionService:
    return _build_session_service(
        database_url_envs=(
            "ADK_VACATION_DATABASE_URL",
            "ADK_WORKBENCH_DATABASE_URL",
            "ADK_DEMO_DATABASE_URL",
            "ADK_DEMO_DB_URL",
            "DATABASE_URL",
        ),
        schema_envs=(
            "ADK_VACATION_DB_SCHEMA",
            "ADK_WORKBENCH_DB_SCHEMA",
            "ADK_DEMO_DB_SCHEMA",
        ),
    )


def _inclusive_days(start_date: date, end_date: date) -> int:
    days = (end_date - start_date).days + 1
    if days <= 0:
        raise ValueError("end_date must be on or after start_date.")
    return days


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

    response = function_response.get("response") or {}
    decided_by = response.get("decided_by")
    manager = EMPLOYEES.get(decided_by) if decided_by else None
    submitted_by = (
        manager.model_dump(mode="json")
        if manager
        else {
            "id": decided_by,
            "name": response.get("decided_by_name"),
        }
    )

    return {
        "submitted_by": submitted_by,
        "payload": {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": function_response["id"],
                        "name": function_response["name"],
                        "response": response,
                    }
                }
            ],
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
    decision: ManagerDecision,
) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=REQUEST_INPUT_FUNCTION_NAME,
                    response=decision.model_dump(mode="json", exclude_none=True),
                )
            )
        ],
    )


def _resume_payload_for_ui(
    interrupt_id: str,
    decision: ManagerDecision,
) -> dict[str, Any]:
    return {
        "role": "user",
        "parts": [
            {
                "functionResponse": {
                    "id": interrupt_id,
                    "name": REQUEST_INPUT_FUNCTION_NAME,
                    "response": decision.model_dump(
                        mode="json",
                        exclude_none=True,
                    ),
                }
            }
        ],
    }


class VacationApprovalRuntime:
    def __init__(
        self,
        session_service_factory: Callable[[], BaseSessionService] | None = None,
    ) -> None:
        _logger.debug("Creating vacation_approval runtime")
        self._session_service_factory = session_service_factory or build_session_service
        self.session_service = self._session_service_factory()
        self.runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self.session_service,
            auto_create_session=True,
        )

    def people(self) -> list[dict[str, Any]]:
        return [employee.model_dump(mode="json") for employee in EMPLOYEES.values()]

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

    async def create_request(
        self,
        payload: CreateVacationRequest,
    ) -> WorkflowRecord:
        if payload.actor_id not in EMPLOYEES:
            raise ValueError("Unknown actor_id.")
        employee = EMPLOYEES[payload.actor_id]
        if employee.manager_id is None:
            raise PermissionError("Only employees with a manager can request PTO.")

        days = _inclusive_days(payload.start_date, payload.end_date)
        request_id = f"vac-{uuid4().hex[:8]}"
        submission = VacationSubmission(
            request_id=request_id,
            employee_id=employee.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            days=days,
            reason=payload.reason,
        )
        content = _build_user_content(submission.model_dump(mode="json"))
        _logger.debug("Creating vacation_approval request with content %s", content)
        return await self._run_workflow(
            session_user_id=employee.id,
            session_id=request_id,
            content=content,
        )

    async def submit_manager_decision(
        self,
        request_id: str,
        payload: SubmitManagerDecisionRequest,
    ) -> WorkflowRecord:
        _logger.debug("In submit_manager_decision...")
        record = await self.get_record(request_id)
        _logger.debug(f"Record {record}")

        if record.pending_input is None:
            raise ValueError("This request is not waiting for manager input.")
        if payload.actor_id != record.manager_id:
            raise PermissionError("Only the assigned manager can approve this request.")

        manager = EMPLOYEES[payload.actor_id]
        _logger.debug("Manager id is %s", manager.id)

        decision = ManagerDecision(
            approved=payload.approved,
            approved_days=payload.approved_days,
            comment=payload.comment,
            decided_by=manager.id,
            decided_by_name=manager.name,
        )
        interrupt_id = record.pending_input["interrupt_id"]
        content = _build_resume_content(interrupt_id, decision)
        _logger.debug("Submitting vacation_approval request %s with content %s", record, content)
        return await self._run_workflow(
            session_user_id=record.session_user_id,
            session_id=record.session_id,
            content=content,
        )

    async def visible_records(self, actor_id: str) -> list[WorkflowRecord]:
        if actor_id not in EMPLOYEES:
            raise ValueError("Unknown actor_id.")
        records = await self._materialize_all_records()
        visible = [
            record
            for record in records
            if record.employee_id == actor_id or record.manager_id == actor_id
        ]
        return sorted(visible, key=lambda record: record.created_at, reverse=True)

    async def get_record(self, request_id: str) -> WorkflowRecord:
        session_refs = await self.session_service.list_sessions(app_name=APP_NAME)
        matches = [
            session
            for session in session_refs.sessions
            if session.id == request_id
        ]
        if not matches:
            raise KeyError("Unknown request_id.")
        if len(matches) > 1:
            raise ValueError(f"Multiple sessions found for request_id {request_id}.")

        session_ref = matches[0]
        session = await self.session_service.get_session(
            app_name=APP_NAME,
            user_id=session_ref.user_id,
            session_id=session_ref.id,
        )
        if session is None:
            raise KeyError("Unknown request_id.")
        return self._materialize_record(session)

    async def _materialize_all_records(self) -> list[WorkflowRecord]:
        response = await self.session_service.list_sessions(app_name=APP_NAME)
        records: list[WorkflowRecord] = []
        for session_ref in response.sessions:
            session = await self.session_service.get_session(
                app_name=APP_NAME,
                user_id=session_ref.user_id,
                session_id=session_ref.id,
            )
            if session is not None:
                records.append(self._materialize_record(session))
        return records

    def _materialize_record(self, session: Any) -> WorkflowRecord:
        events = [_event_to_record(event) for event in session.events]
        request = (
            jsonable_encoder(session.state.get("request"))
            if _is_mapping(session.state)
            else None
        )
        final_decision = (
            jsonable_encoder(session.state.get("decision"))
            if _is_mapping(session.state)
            else None
        )
        pending_input: dict[str, Any] | None = None
        resolved_interrupt_ids: set[str] = set()
        resume_payloads: list[dict[str, Any]] = []

        for event_record in events:
            output = event_record.get("output")
            if _is_mapping(output):
                if output.get("requires_manager_approval") is not None:
                    request = output
                if output.get("decision_source") is not None:
                    final_decision = output

            request_input = _extract_request_input(event_record)
            if request_input is not None:
                pending_input = request_input

            resume_payload = _extract_resume_payload(event_record)
            if resume_payload is not None:
                resume_payloads.append(resume_payload)
                function_response = event_record["function_response"]
                resolved_interrupt_ids.add(function_response["id"])

        if (
            pending_input is not None
            and pending_input["interrupt_id"] in resolved_interrupt_ids
        ):
            pending_input = None

        if final_decision is not None:
            status = final_decision.get("status", "completed")
            pending_input = None
        elif pending_input is not None:
            status = "pending_manager"
        elif resolved_interrupt_ids:
            status = "decision_submitted"
        else:
            status = "running"

        employee_id = (
            (request or {}).get("employee_id")
            or (final_decision or {}).get("employee_id")
            or session.user_id
        )
        employee = EMPLOYEES.get(employee_id)
        manager_id = (
            (request or {}).get("manager_id")
            or (final_decision or {}).get("manager_id")
            or (employee.manager_id if employee else None)
            or ""
        )

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

        return WorkflowRecord(
            request_id=(request or final_decision or {}).get("request_id", session.id),
            session_id=session.id,
            session_user_id=session.user_id,
            employee_id=employee_id,
            manager_id=manager_id,
            status=status,
            request=request,
            pending_input=pending_input,
            final_decision=final_decision,
            events=events,
            resume_payloads=resume_payloads,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def _run_workflow(
        self,
        session_user_id: str,
        session_id: str,
        content: types.Content,
    ) -> WorkflowRecord:
        _logger.debug(f"In _run_and_apply_events: content {content}")

        async for event in self.runner.run_async(
            user_id=session_user_id,
            session_id=session_id,
            new_message=content,
        ):
            _logger.debug("Event Record %s", _event_to_record(event))

        return await self.get_record(session_id)


runtime = VacationApprovalRuntime()
