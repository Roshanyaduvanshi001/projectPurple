"""
ingestion.py — Event ingest: validate → deduplicate → persist → refresh sessions.
 
Key guarantees:
- Idempotent by event_id (ON CONFLICT IGNORE)
- Partial success: malformed events return errors without aborting the batch
- Session table refreshed asynchronously after batch commit
"""
 
from __future__ import annotations
 
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
 
from pydantic import ValidationError
 
from app.database import db_transaction, get_db, refresh_session
from app.models import IngestRequest, IngestResult, StoreEventIn
 
log = logging.getLogger("ingestion")
 
 
def _parse_ts(iso: str) -> float:
    """Parse ISO-8601 to Unix timestamp. Raises ValueError on bad format."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
 
 
async def ingest_events(request: IngestRequest) -> IngestResult:
    """
    Validate, deduplicate, and persist a batch of events.
    Returns IngestResult with accepted / rejected / duplicate counts.
    """
    accepted  = 0
    rejected  = 0
    duplicate = 0
    errors:   list[dict[str, Any]] = []
 
    # ── Validate ──────────────────────────────────────────────────────────────
    valid_rows: list[tuple] = []
    visitor_set: set[tuple[str, str]] = set()   # (store_id, visitor_id) pairs
 
    for idx, ev in enumerate(request.events):
        try:
            ts = _parse_ts(ev.timestamp)
        except (ValueError, TypeError) as e:
            errors.append({
                "index":    idx,
                "event_id": getattr(ev, "event_id", None),
                "error":    f"Invalid timestamp: {e}",
            })
            rejected += 1
            continue
 
        valid_rows.append((
            ev.event_id,
            ev.store_id,
            ev.camera_id,
            ev.visitor_id,
            ev.event_type,
            ts,
            ev.timestamp,
            ev.zone_id,
            ev.dwell_ms,
            int(ev.is_staff),
            ev.confidence,
            ev.metadata.queue_depth,
            ev.metadata.sku_zone,
            ev.metadata.session_seq,
        ))
        visitor_set.add((ev.store_id, ev.visitor_id))
 
    if not valid_rows:
        return IngestResult(
            accepted=0, rejected=rejected, duplicate=0, errors=errors
        )
 
    # ── Persist (idempotent) ─────────────────────────────────────────────────
    conn = get_db()
    # Use executemany with INSERT OR IGNORE for idempotency
    try:
        results = []
        async with db_transaction() as conn:
            for row in valid_rows:
                async with conn.execute(
                    """INSERT OR IGNORE INTO events
                       (event_id, store_id, camera_id, visitor_id, event_type,
                        ts, timestamp, zone_id, dwell_ms, is_staff, confidence,
                        queue_depth, sku_zone, session_seq)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    row,
                ) as cur:
                    if cur.rowcount == 0:
                        duplicate += 1
                    else:
                        accepted += 1
 
    except Exception as exc:
        log.error("DB write failed: %s", exc)
        raise
 
    # ── Refresh sessions asynchronously ──────────────────────────────────────
    asyncio.create_task(_refresh_sessions(visitor_set))
 
    log.info(
        "Ingest batch: accepted=%d duplicate=%d rejected=%d",
        accepted, duplicate, rejected,
    )
    return IngestResult(
        accepted=accepted,
        rejected=rejected,
        duplicate=duplicate,
        errors=errors,
    )
 
 
async def _refresh_sessions(visitor_set: set[tuple[str, str]]) -> None:
    """Background task: update sessions table for all affected visitors."""
    try:
        for store_id, visitor_id in visitor_set:
            await refresh_session(store_id, visitor_id)
        conn = get_db()
        await conn.commit()
    except Exception as exc:
        log.error("Session refresh error: %s", exc)
 