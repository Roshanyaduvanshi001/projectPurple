
"""
emit.py — Event schema (Pydantic) + EventEmitter.
 
All pipeline events are created via this module so that schema compliance
is enforced at the source — not just at the API boundary.
"""
 
from __future__ import annotations
 
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
 
import httpx
from pydantic import BaseModel, Field, field_validator
 
log = logging.getLogger("emit")
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Event schema  (matches the challenge spec exactly)
# ──────────────────────────────────────────────────────────────────────────────
 
class EventMetadata(BaseModel):
    queue_depth: Optional[int]  = None
    sku_zone:    Optional[str]  = None
    session_seq: int            = 0
 
 
class StoreEvent(BaseModel):
    event_id:   str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id:   str
    camera_id:  str
    visitor_id: str
    event_type: str
    timestamp:  str
    zone_id:    Optional[str]  = None
    dwell_ms:   int            = 0
    is_staff:   bool           = False
    confidence: float
    metadata:   EventMetadata  = Field(default_factory=EventMetadata)
 
    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        valid = {
            "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
            "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
        }
        if v not in valid:
            raise ValueError(f"Unknown event_type: {v}")
        return v
 
    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))
 
 
def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
 
# ──────────────────────────────────────────────────────────────────────────────
# EventEmitter
# ──────────────────────────────────────────────────────────────────────────────
 
class EventEmitter:
    """
    Thread-safe event emitter.
    - Writes NDJSON to `output_path` (always).
    - Optionally streams batches to `api_url` (POST /events/ingest).
    """
 
    def __init__(
        self,
        output_path: Path,
        api_url: Optional[str] = None,
        batch_size: int = 50,
    ) -> None:
        self._path        = output_path
        self._api_url     = api_url
        self._batch_size  = batch_size
        self._buffer:  list[StoreEvent]  = []
        self._lock     = threading.Lock()
        self._count    = 0
        self._file     = open(output_path, "w")  # noqa: SIM115
        self._client   = httpx.Client(timeout=10) if api_url else None
 
    @property
    def count(self) -> int:
        return self._count
 
    def _write(self, event: StoreEvent) -> None:
        """Append event to JSONL file and buffer for API upload."""
        line = event.model_dump_json()
        self._file.write(line + "\n")
        self._file.flush()
        self._count += 1
 
        if self._api_url:
            self._buffer.append(event)
            if len(self._buffer) >= self._batch_size:
                self._upload_batch()
 
    def _upload_batch(self) -> None:
        if not self._buffer or not self._client:
            return
        batch       = self._buffer[:]
        self._buffer = []
        payload = [e.model_dump() for e in batch]
        try:
            resp = self._client.post(
                f"{self._api_url}/events/ingest",
                json={"events": payload},
            )
            if resp.status_code not in (200, 201, 207):
                log.warning("API ingest returned %d", resp.status_code)
        except Exception as exc:
            log.error("API ingest failed: %s", exc)
 
    def flush(self) -> None:
        with self._lock:
            self._upload_batch()
            self._file.flush()
 
    def close(self) -> None:
        self.flush()
        self._file.close()
        if self._client:
            self._client.close()
 
    # ── Convenience emit methods (one per event type) ─────────────────────────
 
    def _base(
        self,
        *,
        event_type: str,
        store_id: str,
        camera_id: str,
        visitor_id: str,
        is_staff: bool,
        confidence: float,
        frame_ts: float,
        zone_id: Optional[str] = None,
        dwell_ms: int = 0,
        session_seq: int = 0,
        queue_depth: Optional[int] = None,
        sku_zone: Optional[str] = None,
    ) -> StoreEvent:
        ev = StoreEvent(
            store_id   = store_id,
            camera_id  = camera_id,
            visitor_id = visitor_id,
            event_type = event_type,
            timestamp  = _utc_iso(frame_ts),
            zone_id    = zone_id,
            dwell_ms   = dwell_ms,
            is_staff   = is_staff,
            confidence = confidence,
            metadata   = EventMetadata(
                queue_depth = queue_depth,
                sku_zone    = sku_zone,
                session_seq = session_seq,
            ),
        )
        with self._lock:
            self._write(ev)
        return ev
 
    def emit_entry(self, **kw) -> StoreEvent:
        return self._base(event_type="ENTRY", zone_id=None, dwell_ms=0, **kw)
 
    def emit_exit(self, **kw) -> StoreEvent:
        return self._base(event_type="EXIT", zone_id=None, dwell_ms=0, **kw)
 
    def emit_zone_enter(self, zone_id: str, **kw) -> StoreEvent:
        return self._base(event_type="ZONE_ENTER", zone_id=zone_id, dwell_ms=0, **kw)
 
    def emit_zone_exit(self, zone_id: str, dwell_ms: int, **kw) -> StoreEvent:
        return self._base(event_type="ZONE_EXIT", zone_id=zone_id, dwell_ms=dwell_ms, **kw)
 
    def emit_zone_dwell(self, zone_id: str, dwell_ms: int, **kw) -> StoreEvent:
        return self._base(event_type="ZONE_DWELL", zone_id=zone_id, dwell_ms=dwell_ms, **kw)
 
    def emit_billing_queue_join(self, queue_depth: int, **kw) -> StoreEvent:
        return self._base(
            event_type="BILLING_QUEUE_JOIN",
            zone_id="BILLING",
            queue_depth=queue_depth,
            **kw,
        )
 
    def emit_billing_abandon(self, **kw) -> StoreEvent:
        return self._base(
            event_type="BILLING_QUEUE_ABANDON",
            zone_id="BILLING",
            **kw,
        )
 
    def emit_reentry(self, **kw) -> StoreEvent:
        return self._base(event_type="REENTRY", zone_id=None, dwell_ms=0, **kw)