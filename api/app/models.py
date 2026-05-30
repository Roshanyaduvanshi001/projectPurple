
"""
models.py — All Pydantic models for the Intelligence API.
 
Covers:
- Ingest request / response
- Metrics response
- Funnel response
- Heatmap response
- Anomaly response
- Health response
"""
 
from __future__ import annotations
 
from enum import Enum
from typing import Any, Optional
 
from pydantic import BaseModel, Field, field_validator
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Shared / ingest
# ──────────────────────────────────────────────────────────────────────────────
 
class EventMetadataIn(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone:    Optional[str] = None
    session_seq: int           = 0
 
 
class StoreEventIn(BaseModel):
    event_id:   str
    store_id:   str
    camera_id:  str
    visitor_id: str
    event_type: str
    timestamp:  str           # ISO-8601
    zone_id:    Optional[str] = None
    dwell_ms:   int           = 0
    is_staff:   bool          = False
    confidence: float
    metadata:   EventMetadataIn = Field(default_factory=EventMetadataIn)
 
    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        valid = {
            "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
            "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
        }
        if v not in valid:
            raise ValueError(f"Unknown event_type '{v}'")
        return v
 
    @field_validator("confidence")
    @classmethod
    def clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))
 
 
class IngestRequest(BaseModel):
    events: list[StoreEventIn] = Field(..., max_length=500)
 
 
class IngestResult(BaseModel):
    accepted:  int
    rejected:  int
    duplicate: int
    errors:    list[dict[str, Any]] = []
 
 
# ──────────────────────────────────────────────────────────────────────────────
# /metrics
# ──────────────────────────────────────────────────────────────────────────────
 
class ZoneDwellStat(BaseModel):
    zone_id:      str
    avg_dwell_ms: float
    visit_count:  int
 
 
class MetricsResponse(BaseModel):
    store_id:          str
    window_start:      str
    window_end:        str
    unique_visitors:   int
    conversion_rate:   float          # 0.0–1.0
    avg_basket_inr:    Optional[float]
    queue_depth_now:   int
    abandonment_rate:  float
    zone_dwell:        list[ZoneDwellStat]
 
 
# ──────────────────────────────────────────────────────────────────────────────
# /funnel
# ──────────────────────────────────────────────────────────────────────────────
 
class FunnelStage(BaseModel):
    stage:     str
    count:     int
    drop_pct:  float   # % drop from previous stage; 0 for first stage
 
 
class FunnelResponse(BaseModel):
    store_id: str
    window:   str
    stages:   list[FunnelStage]
 
 
# ──────────────────────────────────────────────────────────────────────────────
# /heatmap
# ──────────────────────────────────────────────────────────────────────────────
 
class HeatmapZone(BaseModel):
    zone_id:          str
    visit_count:      int
    avg_dwell_ms:     float
    normalised_score: float    # 0–100
    data_confidence:  bool     # False if < 20 sessions in window
 
 
class HeatmapResponse(BaseModel):
    store_id: str
    window:   str
    zones:    list[HeatmapZone]
 
 
# ──────────────────────────────────────────────────────────────────────────────
# /anomalies
# ──────────────────────────────────────────────────────────────────────────────
 
class AnomalySeverity(str, Enum):
    INFO     = "INFO"
    WARN     = "WARN"
    CRITICAL = "CRITICAL"
 
 
class AnomalyType(str, Enum):
    BILLING_QUEUE_SPIKE = "BILLING_QUEUE_SPIKE"
    CONVERSION_DROP     = "CONVERSION_DROP"
    DEAD_ZONE           = "DEAD_ZONE"
    STALE_FEED          = "STALE_FEED"
    EMPTY_STORE         = "EMPTY_STORE"
 
 
class Anomaly(BaseModel):
    anomaly_id:       str
    anomaly_type:     AnomalyType
    severity:         AnomalySeverity
    detected_at:      str
    description:      str
    suggested_action: str
    metadata:         dict[str, Any] = {}
 
 
class AnomalyResponse(BaseModel):
    store_id:  str
    anomalies: list[Anomaly]
 
 
# ──────────────────────────────────────────────────────────────────────────────
# /health
# ──────────────────────────────────────────────────────────────────────────────
 
class StoreHealth(BaseModel):
    store_id:         str
    last_event_at:    Optional[str]
    lag_seconds:      Optional[float]
    stale_feed:       bool
    event_count_24h:  int
 
 
class HealthResponse(BaseModel):
    status:        str           # "ok" | "degraded" | "error"
    version:       str
    uptime_seconds: float
    stores:        list[StoreHealth]
    db_connected:  bool