# Vacation Approval Interaction Diagrams

These diagrams show how the React UI, FastAPI runtime, ADK workflow, and
Postgres-backed ADK session store interact for the main vacation approval user
journeys.

The API does not keep vacation request records in process memory. It
materializes each visible `WorkflowRecord` from the ADK session store by reading
persisted sessions, events, state, `RequestInput` function calls, and manager
FunctionResponses.

## 1. Rob White Requests 1 Day

```mermaid
sequenceDiagram
    autonumber
    actor Rob as Rob White
    participant UI as React UI
    participant API as FastAPI Runtime
    participant ADK as ADK Runner
    participant WF as vacation_approval Workflow
    participant DB as Postgres adk_store

    Rob->>UI: Submit 1-day PTO request
    UI->>API: POST /api/requests<br/>{actor_id: rob.white, days: 1}
    API->>ADK: run_async(session_id=request_id,<br/>new_message=VacationSubmission)
    ADK->>WF: START -> capture_request
    WF->>DB: Persist user event + request state
    WF->>WF: evaluate_request(days is 1 or less)
    WF-->>ADK: ManagerDecision(auto-approved)
    ADK->>WF: process_decision(request, node_input=ManagerDecision)
    WF->>DB: Persist final decision event + state
    ADK-->>API: FinalVacationDecision(status=approved)
    API->>DB: Materialize WorkflowRecord from ADK session<br/>events + state.decision
    API-->>UI: request.status = approved
    UI-->>Rob: Show auto-approved request
```

## 2. Rob White Requests 5 Days

```mermaid
sequenceDiagram
    autonumber
    actor Rob as Rob White
    participant UI as React UI
    participant API as FastAPI Runtime
    participant ADK as ADK Runner
    participant WF as vacation_approval Workflow
    participant DB as Postgres adk_store
    actor Jason as Jason Brown

    Rob->>UI: Submit 5-day PTO request
    UI->>API: POST /api/requests<br/>{actor_id: rob.white, days: 5}
    API->>ADK: run_async(session_id=request_id,<br/>new_message=VacationSubmission)
    ADK->>WF: START -> capture_request
    WF->>DB: Persist user event + request state
    WF->>WF: evaluate_request(days is more than 1)
    WF-->>ADK: RequestInput(interrupt_id=manager_approval:request_id,<br/>payload.assigned_to=jason.brown,<br/>response_schema=ManagerDecision)
    ADK->>DB: Persist RequestInput function_call event
    ADK-->>API: long_running_tool_ids includes manager_approval:request_id
    API->>DB: Materialize WorkflowRecord from persisted events<br/>pending_input = RequestInput function_call
    API-->>UI: request.status = pending_manager<br/>pending_input assigned to Jason
    UI-->>Rob: Show waiting for manager
    Jason->>UI: Logs in as Jason Brown
    UI->>API: GET /api/requests?actor_id=jason.brown
    API->>DB: list_sessions(app_name)<br/>get_session(session_id)
    API->>API: Rebuild manager-visible records<br/>from session events and state
    API-->>UI: Manager inbox includes Rob's request
```

## 3. Uvicorn Restart While Request Is Pending

```mermaid
sequenceDiagram
    autonumber
    actor User as Rob or Jason
    participant UI as React UI
    participant API1 as FastAPI Runtime A
    participant DB as Postgres adk_store
    participant API2 as FastAPI Runtime B

    User->>UI: Click Restart runtime<br/>or uvicorn process restarts
    UI->>API1: POST /api/runtime/restart
    API1->>API1: Close current session service<br/>rebuild ADK Runner
    Note over API1,DB: No demo records are kept only in memory.<br/>ADK sessions/events/state remain in Postgres.
    UI->>API2: GET /api/requests?actor_id=jason.brown
    API2->>DB: list_sessions(app_name=vacation_approval_demo)
    API2->>DB: get_session(user_id=rob.white,<br/>session_id=request_id)
    API2->>API2: Materialize WorkflowRecord<br/>request = state.request<br/>pending_input = latest unresolved RequestInput
    API2-->>UI: Manager inbox still contains Rob's pending request
```

## 4. Jason Brown Approves

```mermaid
sequenceDiagram
    autonumber
    actor Jason as Jason Brown
    participant UI as React UI
    participant API as FastAPI Runtime
    participant ADK as ADK Runner
    participant WF as vacation_approval Workflow
    participant DB as Postgres adk_store

    Jason->>UI: Approve Rob's 5-day request
    UI->>API: GET /api/requests/{request_id}
    API->>DB: Materialize current WorkflowRecord<br/>from persisted session
    API-->>UI: pending_input.interrupt_id = manager_approval:request_id
    UI->>API: POST /api/requests/{request_id}/decision<br/>{actor_id: jason.brown, approved: true, approved_days: 5}
    API->>DB: get_session(session_id=request_id)
    API->>API: Materialize pending_input from RequestInput event
    API->>API: Verify actor_id == pending_input.payload.assigned_to.id
    API->>ADK: run_async(session_id=request_id,<br/>new_message=functionResponse)
    Note over API,ADK: functionResponse.id = manager_approval:request_id<br/>functionResponse.name = adk_request_input
    ADK->>DB: Match functionResponse to prior RequestInput interrupt
    ADK->>WF: Resume workflow at process_decision
    WF->>WF: process_decision(request,<br/>node_input=ManagerDecision(approved=true))
    WF->>DB: Persist approved decision event + state
    ADK-->>API: FinalVacationDecision(status=approved,<br/>approved_days=5)
    API->>DB: Re-read session and materialize final_decision
    API-->>UI: Updated request with final_decision.node_input
    UI-->>Jason: Show approved decision and ADK resume payload
```

## 5. Jason Brown Rejects

```mermaid
sequenceDiagram
    autonumber
    actor Jason as Jason Brown
    participant UI as React UI
    participant API as FastAPI Runtime
    participant ADK as ADK Runner
    participant WF as vacation_approval Workflow
    participant DB as Postgres adk_store

    Jason->>UI: Reject Rob's 5-day request
    UI->>API: GET /api/requests/{request_id}
    API->>DB: Materialize current WorkflowRecord<br/>from persisted session
    API-->>UI: pending_input.interrupt_id = manager_approval:request_id
    UI->>API: POST /api/requests/{request_id}/decision<br/>{actor_id: jason.brown, approved: false, approved_days: 0}
    API->>DB: get_session(session_id=request_id)
    API->>API: Materialize pending_input from RequestInput event
    API->>API: Verify actor_id == pending_input.payload.assigned_to.id
    API->>ADK: run_async(session_id=request_id,<br/>new_message=functionResponse)
    Note over API,ADK: response = ManagerDecision(approved=false,<br/>approved_days=0, decided_by=jason.brown)
    ADK->>DB: Match functionResponse to manager_approval interrupt
    ADK->>WF: Resume workflow at process_decision
    WF->>WF: process_decision(request,<br/>node_input=ManagerDecision(approved=false))
    WF->>DB: Persist denied decision event + state
    ADK-->>API: FinalVacationDecision(status=denied,<br/>approved_days=0)
    API->>DB: Re-read session and materialize final_decision
    API-->>UI: Updated request with denied final_decision
    UI-->>Jason: Show denied decision and ADK resume payload
```

## Interaction Summary

The important distinction is that the manager does not start a new workflow.
Jason's UI submits a FunctionResponse that references the existing
`RequestInput.interrupt_id`. ADK uses that function response to resume the same
workflow invocation and passes the response body into `process_decision` as
`node_input`.

The second important distinction is persistence. The React UI receives
`WorkflowRecord` objects, but those are read models. They are rebuilt on demand
from ADK's Postgres-backed sessions:

- `state.request` gives the submitted vacation request.
- unresolved `adk_request_input` function calls become `pending_input`.
- user-authored `adk_request_input` FunctionResponses become resume payloads.
- `state.decision` or the final decision output gives the completed approval or
  rejection.

Because of that, a new uvicorn process can list sessions from Postgres,
materialize the same pending request, and let Jason approve or reject it after a
restart.
