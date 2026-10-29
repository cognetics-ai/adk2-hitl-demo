from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .runtimes.vacation_approval import CreateVacationRequest
from .runtimes.vacation_approval import SubmitManagerDecisionRequest
from .runtimes.vacation_approval import runtime

from agents import _logger

_logger.debug("Starting vacation_approval API")
app = FastAPI(title="Vacation Approval ADK Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/api/bootstrap")
async def bootstrap() -> dict:
    _logger.debug("Bootstrap vacation_approval API")
    return {
        "people": runtime.people(),
        "default_actor_id": "rob.white",
    }


@app.get("/api/requests")
async def list_requests(actor_id: str) -> dict:
    try:
        records = await runtime.visible_records(actor_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"requests": [record.model_dump(mode="json") for record in records]}


@app.get("/api/requests/{request_id}")
async def get_request(request_id: str) -> dict:
    try:
        record = await runtime.get_record(request_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"request": record.model_dump(mode="json")}


@app.post("/api/requests")
async def create_request(payload: CreateVacationRequest) -> dict:
    _logger.debug("Creating vacation_approval request with payload %s", payload)
    try:
        record = await runtime.create_request(payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"request": record.model_dump(mode="json")}


@app.post("/api/requests/{request_id}/decision")
async def submit_decision(
    request_id: str,
    payload: SubmitManagerDecisionRequest,
) -> dict:
    _logger.debug("Submitting vacation_approval request with payload %s", payload)
    try:
        record = await runtime.submit_manager_decision(request_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"request": record.model_dump(mode="json")}


@app.post("/api/reset")
async def reset_demo() -> dict:
    await runtime.reset()
    return {"ok": True}


@app.post("/api/runtime/restart")
async def restart_runtime() -> dict:
    await runtime.restart()
    return {"ok": True}
