"""Gateway REST API — FastAPI application.

Serves the ActionCatalog, OpenAPI spec, action execution,
session management, and job submission endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import ActionObject
from packages.openapi_gen.src.generator import OpenAPIGenConfig, generate_openapi, generate_openapi_yaml
from apps.gateway.src.executor import ExecutionRequest, ExecutionResult, Executor
from apps.gateway.src.session import SessionManager, SessionStartRequest
from apps.gateway.src.audit import AuditLogger
from apps.gateway.src.rate_limit import RateLimiter

# Application state
app = FastAPI(
    title="Shadow APK Gateway",
    description="Universal APK-to-Gateway — Execute discovered Android app API endpoints",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory stores (replaced with persistent stores in production)
_catalogs: dict[str, ActionCatalog] = {}
_executor = Executor()
_session_manager = SessionManager()
_audit_logger = AuditLogger()
_rate_limiter = RateLimiter()


def load_catalog(catalog: ActionCatalog) -> None:
    """Load an ActionCatalog into the gateway."""
    _catalogs[catalog.app_id] = catalog


def load_catalog_from_file(path: str | Path) -> ActionCatalog:
    """Load an ActionCatalog from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    catalog = ActionCatalog.model_validate(data)
    load_catalog(catalog)
    return catalog


# === App Routes ===

@app.get("/apps")
async def list_apps():
    """List all indexed apps."""
    return [
        {
            "app_id": c.app_id,
            "package_name": c.package_name,
            "version_name": c.version_name,
            "total_actions": c.total_actions,
            "approved_actions": c.approved_actions,
        }
        for c in _catalogs.values()
    ]


@app.get("/apps/{app_id}")
async def get_app(app_id: str):
    """Get app metadata."""
    catalog = _get_catalog(app_id)
    return {
        "app_id": catalog.app_id,
        "package_name": catalog.package_name,
        "version_name": catalog.version_name,
        "version_code": catalog.version_code,
        "total_actions": catalog.total_actions,
        "approved_actions": catalog.approved_actions,
        "high_confidence_actions": catalog.high_confidence_actions,
        "actions_needing_review": catalog.actions_needing_review,
    }


# === Action Routes ===

@app.get("/apps/{app_id}/actions")
async def list_actions(
    app_id: str,
    confidence_min: float = 0.0,
    approved_only: bool = False,
    risk_tag: Optional[str] = None,
    method: Optional[str] = None,
):
    """List ActionObjects with optional filters."""
    catalog = _get_catalog(app_id)
    actions = catalog.actions

    if approved_only:
        actions = [a for a in actions if a.approved]
    if confidence_min > 0:
        actions = [a for a in actions if a.confidence_score >= confidence_min]
    if risk_tag:
        actions = [a for a in actions if risk_tag in a.risk_tags]
    if method:
        actions = [a for a in actions if a.method == method.upper()]

    return [a.model_dump() for a in actions]


@app.get("/apps/{app_id}/actions/{action_id}")
async def get_action(app_id: str, action_id: str):
    """Get single ActionObject detail."""
    catalog = _get_catalog(app_id)
    action = catalog.get_action(action_id)
    if not action:
        raise HTTPException(404, f"Action {action_id} not found")
    return action.model_dump()


class PatchActionRequest(BaseModel):
    approved: Optional[bool] = None
    approved_by: Optional[str] = None
    notes: Optional[str] = None


@app.patch("/apps/{app_id}/actions/{action_id}")
async def patch_action(app_id: str, action_id: str, body: PatchActionRequest):
    """Approve / annotate an action."""
    catalog = _get_catalog(app_id)
    action = catalog.get_action(action_id)
    if not action:
        raise HTTPException(404, f"Action {action_id} not found")

    if body.approved is not None:
        action.approved = body.approved
    if body.approved_by is not None:
        action.approved_by = body.approved_by
    if body.notes is not None:
        action.notes = body.notes

    return action.model_dump()


# === Execution Routes ===

@app.post("/apps/{app_id}/actions/{action_id}/execute")
async def execute_action(
    app_id: str,
    action_id: str,
    request: Request,
):
    """Execute an action against the real app backend."""
    catalog = _get_catalog(app_id)
    action = catalog.get_action(action_id)
    if not action:
        raise HTTPException(404, f"Action {action_id} not found")

    # Rate limit check
    _rate_limiter.check(app_id, action_id)

    # Parse execution request body
    try:
        body = await request.json()
    except Exception:
        body = {}

    exec_request = ExecutionRequest(
        action=action,
        params=body.get("params", {}),
        tenant_id=body.get("tenant_id", "default"),
    )

    # Get session if available
    session = _session_manager.get_session(app_id, exec_request.tenant_id)

    # Execute
    result = await _executor.execute(exec_request, session)

    # Audit log
    _audit_logger.log_execution(
        app_id=app_id,
        action_id=action_id,
        tenant_id=exec_request.tenant_id,
        request_url=f"{action.base_url}{action.url_template}",
        response_status=result.status_code,
        latency_ms=result.latency_ms,
        error=result.error,
        sensitive_params=[p.name for p in action.params if p.sensitive],
    )

    return result.to_dict()


# === Spec Routes ===

@app.get("/apps/{app_id}/spec.json")
async def get_spec_json(app_id: str):
    """Get OpenAPI 3.1 JSON spec for an app."""
    catalog = _get_catalog(app_id)
    config = OpenAPIGenConfig(include_unapproved=False)
    spec = generate_openapi(catalog, config)
    return JSONResponse(content=spec)


@app.get("/apps/{app_id}/spec.yaml")
async def get_spec_yaml(app_id: str):
    """Get OpenAPI 3.1 YAML spec for an app."""
    catalog = _get_catalog(app_id)
    config = OpenAPIGenConfig(include_unapproved=False)
    spec_yaml = generate_openapi_yaml(catalog, config)
    return Response(content=spec_yaml, media_type="text/yaml")


# === Session Routes ===

@app.post("/apps/{app_id}/sessions/start")
async def start_session(app_id: str, body: SessionStartRequest):
    """Bootstrap a session (login + token store)."""
    catalog = _get_catalog(app_id)
    session = await _session_manager.start_session(
        app_id=app_id,
        tenant_id=body.tenant_id,
        credentials=body.credentials,
        catalog=catalog,
        executor=_executor,
    )
    return {"session_id": session.session_id, "status": "active"}


@app.delete("/apps/{app_id}/sessions/{session_id}")
async def delete_session(app_id: str, session_id: str):
    """Clear a session."""
    _session_manager.clear_session(app_id, session_id)
    return {"status": "cleared"}


# === Job Routes ===

class JobSubmitRequest(BaseModel):
    apk_url: Optional[str] = None
    apk_path: Optional[str] = None


@app.post("/jobs")
async def submit_job(body: JobSubmitRequest):
    """Submit an APK for analysis."""
    # This integrates with the orchestrator
    import uuid
    job_id = str(uuid.uuid4())
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "APK submitted for analysis",
    }


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get job status."""
    return {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
    }


# === Helpers ===

def _get_catalog(app_id: str) -> ActionCatalog:
    """Retrieve a catalog or raise 404."""
    if app_id not in _catalogs:
        raise HTTPException(404, f"App {app_id} not found")
    return _catalogs[app_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
