from __future__ import annotations

from datetime import date
from typing import Literal, Generator

from google.adk import Event
from google.adk import Workflow
from google.adk.agents.context import Context
from google.adk.events import RequestInput
from pydantic import BaseModel
from pydantic import Field
from agents import _logger


AUTO_APPROVAL_MAX_DAYS = 1


class Employee(BaseModel):
    id: str
    name: str
    title: str
    manager_id: str | None = None


EMPLOYEES: dict[str, Employee] = {
    "rob.white": Employee(
        id="rob.white",
        name="Rob White",
        title="Investment Banking Associate",
        manager_id="jason.brown",
    ),
    "jason.brown": Employee(
        id="jason.brown",
        name="Jason Brown",
        title="Managing Director",
    ),
}


class VacationSubmission(BaseModel):
    request_id: str = Field(description="Workflow request id assigned by the app.")
    employee_id: str = Field(description="Employee submitting the request.")
    start_date: date
    end_date: date
    days: int = Field(gt=0, description="Number of vacation days requested.")
    reason: str = Field(min_length=3)


class VacationRequest(BaseModel):
    request_id: str
    employee_id: str
    employee_name: str
    employee_title: str
    manager_id: str
    manager_name: str
    manager_title: str
    start_date: date
    end_date: date
    days: int
    reason: str
    requires_manager_approval: bool
    policy: dict[str, int | str]


class ManagerDecision(BaseModel):
    approved: bool = Field(description="Whether the manager approves the request.")
    approved_days: int | None = Field(
        default=None,
        ge=0,
        description="Number of days approved. Required when approved is true.",
    )
    comment: str | None = Field(
        default=None,
        description="Manager comment visible in the audit trail.",
    )
    decided_by: str | None = Field(
        default=None,
        description="Manager employee id supplied by the approving UI.",
    )
    decided_by_name: str | None = Field(
        default=None,
        description="Manager name supplied by the approving UI.",
    )


class FinalVacationDecision(BaseModel):
    request_id: str
    status: Literal["approved", "denied"]
    requested_days: int
    approved_days: int
    employee_id: str
    employee_name: str
    manager_id: str
    manager_name: str
    decision_source: Literal["auto_policy", "manager_review"]
    comment: str | None
    node_input: ManagerDecision


def build_vacation_request(submission: VacationSubmission) -> VacationRequest:
    employee = EMPLOYEES[submission.employee_id]
    if employee.manager_id is None:
        raise ValueError(f"{employee.name} does not have a manager configured.")
    manager = EMPLOYEES[employee.manager_id]
    requires_manager = submission.days > AUTO_APPROVAL_MAX_DAYS

    return VacationRequest(
        request_id=submission.request_id,
        employee_id=employee.id,
        employee_name=employee.name,
        employee_title=employee.title,
        manager_id=manager.id,
        manager_name=manager.name,
        manager_title=manager.title,
        start_date=submission.start_date,
        end_date=submission.end_date,
        days=submission.days,
        reason=submission.reason,
        requires_manager_approval=requires_manager,
        policy={
            "auto_approval_max_days": AUTO_APPROVAL_MAX_DAYS,
            "manager_review_rule": "Requests over 1 day require manager approval.",
        },
    )


def capture_request(ctx: Context, node_input: VacationSubmission) -> Event:
    _logger.debug(f"Capture request: {node_input}")
    request = build_vacation_request(node_input)
    _logger.debug(f"Built request: {request}. Storing in context...")
    ctx.state["request"] = request.model_dump(mode="json")

    return Event(
        message=(
            f"{request.employee_name} submitted {request.days} vacation days "
            f"from {request.start_date.isoformat()} to {request.end_date.isoformat()}."
        ),
        output=request.model_dump(mode="json"),
    )


def evaluate_request(request: VacationRequest):
    _logger.debug(f"In Evaluate request: {request}")
    if request.days <= AUTO_APPROVAL_MAX_DAYS:
        yield ManagerDecision(
            approved=True,
            approved_days=request.days,
            comment="Auto-approved because the request is 1 day or less.",
            decided_by="policy:auto_approval",
            decided_by_name="Auto Approval Policy",
        )
        return
    _logger.debug(f"Yielding...................")

    yield RequestInput(
        interrupt_id=f"manager_approval:{request.request_id}",
        message=(
            f"{request.manager_name}, please review {request.employee_name}'s "
            f"{request.days}-day vacation request."
        ),
        payload={
            "request": request.model_dump(mode="json"),
            "assigned_to": {
                "id": request.manager_id,
                "name": request.manager_name,
                "title": request.manager_title,
            },
            "submitted_by": {
                "id": request.employee_id,
                "name": request.employee_name,
                "title": request.employee_title,
            },
            "policy": request.policy,
        },
        response_schema=ManagerDecision,
    )

# Parse the Resumed Input: When the workflow resumes, the node_input to the next node will be the parsed Pydantic model
# implicitly (if type-hinted).

def process_decision(
    ctx: Context,
    request: VacationRequest,
    node_input: ManagerDecision,
) -> Event:
    _logger.debug(f"Resuming workflow...Processing manager decision: {node_input}")
    approved_days = node_input.approved_days
    if node_input.approved and approved_days is None:
        approved_days = request.days
    if not node_input.approved:
        approved_days = 0

    decision_source: Literal["auto_policy", "manager_review"] = (
        "auto_policy"
        if node_input.decided_by == "policy:auto_approval"
        else "manager_review"
    )

    decision = FinalVacationDecision(
        request_id=request.request_id,
        status="approved" if node_input.approved else "denied",
        requested_days=request.days,
        approved_days=approved_days or 0,
        employee_id=request.employee_id,
        employee_name=request.employee_name,
        manager_id=request.manager_id,
        manager_name=request.manager_name,
        decision_source=decision_source,
        comment=node_input.comment,
        node_input=node_input,
    )
    ctx.state["decision"] = decision.model_dump(mode="json")

    return Event(
        message=(
            f"process_decision received node_input from "
            f"{node_input.decided_by_name or node_input.decided_by}: "
            f"{node_input.model_dump(mode='json', exclude_none=True)}"
        ),
        output=decision.model_dump(mode="json"),
    )


root_agent = Workflow(
    name="vacation_approval",
    edges=[
        ("START", capture_request, evaluate_request, process_decision),
    ],
)
