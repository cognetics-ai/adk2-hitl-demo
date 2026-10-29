from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from agents import _logger
from data.sec_tools import lookup_company

from .research_services import ResearchWorkflowRequest
from .research_services import SubmitCompsPeerReviewRequest
from .research_services import research_service
from .runtimes.mna_dcf_valuation import CreateDcfWorkflowRequest
from .runtimes.mna_dcf_valuation import RunMonteCarloRequest
from .runtimes.mna_dcf_valuation import SubmitDcfAssumptionsRequest
from .runtimes.mna_dcf_valuation import runtime


app = FastAPI(title="M&A DCF Valuation ADK Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
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
    return runtime.bootstrap()


@app.get("/api/workflows")
async def list_workflows(actor_id: str) -> dict:
    try:
        records = await runtime.visible_records(actor_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflows": [record.model_dump(mode="json") for record in records]}


@app.get("/api/workflows/{request_id}")
async def get_workflow(request_id: str) -> dict:
    try:
        record = await runtime.get_record(request_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.post("/api/workflows")
async def create_workflow(payload: CreateDcfWorkflowRequest) -> dict:
    _logger.info("Creating DCF workflow with payload %s", payload)
    try:
        record = await runtime.create_workflow(payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.post("/api/workflows/{request_id}/assumptions")
async def submit_assumptions(
    request_id: str,
    payload: SubmitDcfAssumptionsRequest,
) -> dict:
    _logger.info("Submitting DCF assumptions for %s", payload)
    try:
        record = await runtime.submit_assumptions(request_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.post("/api/workflows/{request_id}/monte-carlo")
async def run_monte_carlo(request_id: str, payload: RunMonteCarloRequest) -> dict:
    _logger.info(f"Running Monte Carlo for request id {request_id} and payload {payload}")
    try:
        record = await runtime.run_monte_carlo(request_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.post("/api/company-background")
async def start_company_background(payload: ResearchWorkflowRequest) -> dict:
    _logger.info("Starting company background workflow with payload %s", payload)
    try:
        record = research_service.start_company_background(payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.get("/api/company-background/{job_id}")
async def get_company_background(job_id: str) -> dict:
    _logger.debug(f"Getting company background with job_id {job_id}")
    try:
        record = research_service.get_job(job_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.post("/api/comparables")
async def start_comparables(payload: ResearchWorkflowRequest) -> dict:
    _logger.debug(f"Starting comparable workflow with payload: {payload}")
    try:
        record = research_service.start_comparables(payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.get("/api/comparables/{job_id}")
async def get_comparables(job_id: str) -> dict:
    _logger.debug(f"Getting comparable workflow with job_id {job_id}")
    try:
        record = research_service.get_job(job_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.get("/api/company-lookup")
async def lookup_company_details(query: str) -> dict:
    cleaned = query.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Company name or ticker is required.")
    try:
        result = lookup_company(cleaned)
    except Exception as exc:
        raise _http_error(exc) from exc
    if result.get("status") != "success":
        return result
    best = result["best_match"]
    return {
        **result,
        "company_name": best["title"],
        "ticker": best["ticker"],
        "exchange": None,
        "country": "United States",
        "cik": best["cik"],
        "cik_padded": best["cik_padded"],
    }


@app.post("/api/comparables/{job_id}/peers")
async def submit_comparable_peers(
    job_id: str,
    payload: SubmitCompsPeerReviewRequest,
) -> dict:
    _logger.debug("Submitting comparable peer review for %s with payload %s", job_id, payload)
    try:
        record = await research_service.submit_comparable_peers(job_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"workflow": record.model_dump(mode="json")}


@app.get("/api/comparables/{job_id}/excel")
async def download_comparables_excel(job_id: str) -> FileResponse:
    try:
        record = research_service.get_job(job_id)
        artifact = record.comps_excel_artifact
        if not artifact:
            raise ValueError("Comparables Excel artifact is not available yet.")
        return FileResponse(
            artifact["path"],
            media_type=artifact["mime_type"],
            filename=artifact["filename"],
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/api/reset")
async def reset_demo() -> dict:
    await runtime.reset()
    await research_service.reset()
    return {"ok": True}


@app.post("/api/runtime/restart")
async def restart_runtime() -> dict:
    await runtime.restart()
    await research_service.restart()
    return {"ok": True}
