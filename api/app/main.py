
"""
main.py — FastAPI entrypoint for the Store Intelligence API.
 
Routes:
  POST /events/ingest
  GET  /stores/{store_id}/metrics
  GET  /stores/{store_id}/funnel
  GET  /stores/{store_id}/heatmap
  GET  /stores/{store_id}/anomalies
  GET  /health
  WS   /ws/live/{store_id}   (real-time metric push every 5s)
 
Middleware:
  - Structured JSON logging (trace_id, store_id, latency_ms)
  - Global exception handler (no raw tracebacks in responses)
  - DB unavailable → 503
 
Production notes:
  - Swap aiosqlite for asyncpg for multi-worker deployments
  - Add rate limiting via slowapi or nginx upstream
"""
 
from __future__ import annotations
 
import asyncio
import json
import logging
import os
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
 
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
 
from app.anomalies import detect_anomalies
from app.database import close_db, init_db, load_pos_csv
from app.funnel import get_funnel, get_heatmap
from app.health import get_health
from app.ingestion import ingest_events
from app.metrics import get_store_metrics
from app.models import IngestRequest
 
# ──────────────────────────────────────────────────────────────────────────────
# Logging — structured JSON to stdout
# ──────────────────────────────────────────────────────────────────────────────
 
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {
            "ts":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d)
 
 
handler = logging.StreamHandler()
handler.setFormatter(_JsonFormatter())
logging.root.setLevel(logging.INFO)
logging.root.handlers = [handler]
log = logging.getLogger("api")
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Startup / shutdown
# ──────────────────────────────────────────────────────────────────────────────
 
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    await init_db()
    pos_path = Path(os.getenv("POS_CSV_PATH", "/data/pos_transactions.csv"))
    await load_pos_csv(pos_path)
    log.info("API startup complete")
    yield
    await close_db()
    log.info("API shutdown complete")
 
 
# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────
 
app = FastAPI(
    title="Store Intelligence API",
    version="1.0.0",
    description="Offline retail analytics from CCTV + POS",
    lifespan=lifespan,
)
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Structured request logging middleware
# ──────────────────────────────────────────────────────────────────────────────
 
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    request.state.trace_id = trace_id
 
    # Extract store_id from path if present
    path_parts = request.url.path.split("/")
    store_id   = None
    if "stores" in path_parts:
        idx = path_parts.index("stores")
        if idx + 1 < len(path_parts):
            store_id = path_parts[idx + 1]
 
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        latency  = round((time.perf_counter() - t0) * 1000, 2)
        log.info(json.dumps({
            "trace_id":    trace_id,
            "method":      request.method,
            "endpoint":    request.url.path,
            "store_id":    store_id,
            "status_code": response.status_code,
            "latency_ms":  latency,
        }))
        response.headers["X-Trace-Id"]   = trace_id
        response.headers["X-Latency-Ms"] = str(latency)
        return response
    except Exception as exc:
        latency = round((time.perf_counter() - t0) * 1000, 2)
        log.error(json.dumps({
            "trace_id":  trace_id,
            "endpoint":  request.url.path,
            "error":     str(exc),
            "latency_ms": latency,
        }))
        raise
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Global exception handlers — no raw tracebacks in responses
# ──────────────────────────────────────────────────────────────────────────────
 
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "unknown")
    log.error("Unhandled exception trace=%s: %s", trace_id, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error":    "internal_server_error",
            "message":  "An unexpected error occurred",
            "trace_id": trace_id,
        },
    )
 
 
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )
 
 
def _db_error_response(trace_id: str):
    return JSONResponse(
        status_code=503,
        content={
            "error":    "service_unavailable",
            "message":  "Database unavailable — please retry",
            "trace_id": trace_id,
        },
    )
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
 
@app.post("/events/ingest", status_code=207)
async def ingest(request: Request, body: IngestRequest):
    """
    Ingest a batch of up to 500 events.
    Idempotent by event_id. Returns 207 Multi-Status with per-batch summary.
    """
    try:
        result = await ingest_events(body)
    except RuntimeError as e:
        if "not initialised" in str(e):
            return _db_error_response(request.state.trace_id)
        raise
    except Exception:
        return _db_error_response(request.state.trace_id)
 
    log.info(json.dumps({
        "endpoint":    "/events/ingest",
        "event_count": len(body.events),
        "accepted":    result.accepted,
        "rejected":    result.rejected,
        "duplicate":   result.duplicate,
    }))
    return result
 
 
@app.get("/stores/{store_id}/metrics")
async def store_metrics(store_id: str, request: Request):
    try:
        return await get_store_metrics(store_id)
    except RuntimeError:
        return _db_error_response(request.state.trace_id)
 
 
@app.get("/stores/{store_id}/funnel")
async def store_funnel(store_id: str, request: Request):
    try:
        return await get_funnel(store_id)
    except RuntimeError:
        return _db_error_response(request.state.trace_id)
 
 
@app.get("/stores/{store_id}/heatmap")
async def store_heatmap(store_id: str, request: Request):
    try:
        return await get_heatmap(store_id)
    except RuntimeError:
        return _db_error_response(request.state.trace_id)
 
 
@app.get("/stores/{store_id}/anomalies")
async def store_anomalies(store_id: str, request: Request):
    try:
        return await detect_anomalies(store_id)
    except RuntimeError:
        return _db_error_response(request.state.trace_id)
 
 
@app.get("/health")
async def health():
    return await get_health()
 
 
# ──────────────────────────────────────────────────────────────────────────────
# WebSocket live feed — Part E
# ──────────────────────────────────────────────────────────────────────────────
 
_ws_connections: dict[str, list[WebSocket]] = {}
 
 
@app.websocket("/ws/live/{store_id}")
async def live_feed(websocket: WebSocket, store_id: str):
    """
    Push live metrics to connected dashboards every 5 seconds.
    Automatically removed on disconnect.
    """
    await websocket.accept()
    _ws_connections.setdefault(store_id, []).append(websocket)
    log.info("WebSocket connected: store=%s", store_id)
    try:
        while True:
            metrics   = await get_store_metrics(store_id)
            anomalies = await detect_anomalies(store_id)
            payload   = {
                "type":      "metrics_update",
                "store_id":  store_id,
                "metrics":   metrics.model_dump(),
                "anomalies": [a.model_dump() for a in anomalies.anomalies],
                "ts":        time.time(),
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        log.info("WebSocket disconnected: store=%s", store_id)
    finally:
        _ws_connections.get(store_id, []).remove(websocket)
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_config=None,   # we handle logging ourselves
    )
