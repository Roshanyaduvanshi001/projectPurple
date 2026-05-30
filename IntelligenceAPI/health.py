
"""
health.py — /health endpoint.
 
Checks:
- Database reachability
- Per-store last event timestamp + lag
- STALE_FEED flag if lag > 10 min
"""
 
from __future__ import annotations
 
import logging
import time
from datetime import datetime, timezone
 
from app.database import get_db
from app.models import HealthResponse, StoreHealth
 
log = logging.getLogger("health")
 
STALE_THRESHOLD_SECONDS = 600   # 10 minutes
APP_VERSION              = "1.0.0"
_start_time              = time.time()
 
 
async def get_health() -> HealthResponse:
    now      = time.time()
    db_ok    = True
    stores:  list[StoreHealth] = []
 
    try:
        conn = get_db()
 
        # All known stores
        async with conn.execute(
            "SELECT DISTINCT store_id FROM events"
        ) as cur:
            store_ids = [r["store_id"] for r in await cur.fetchall()]
 
        for store_id in store_ids:
            # Last event timestamp
            async with conn.execute(
                "SELECT MAX(ts) as last_ts FROM events WHERE store_id=?",
                (store_id,),
            ) as cur:
                row     = await cur.fetchone()
                last_ts = float(row["last_ts"]) if row and row["last_ts"] else None
 
            # 24h event count
            async with conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE store_id=? AND ts > ?",
                (store_id, now - 86_400),
            ) as cur:
                row   = await cur.fetchone()
                cnt24 = int(row["cnt"] or 0)
 
            lag_s  = (now - last_ts) if last_ts else None
            stale  = bool(lag_s is None or lag_s > STALE_THRESHOLD_SECONDS)
            last_iso = (
                datetime.fromtimestamp(last_ts, tz=timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
                if last_ts else None
            )
 
            stores.append(StoreHealth(
                store_id=store_id,
                last_event_at=last_iso,
                lag_seconds=round(lag_s, 1) if lag_s is not None else None,
                stale_feed=stale,
                event_count_24h=cnt24,
            ))
 
    except Exception as exc:
        log.error("Health check DB error: %s", exc)
        db_ok = False
 
    status = "ok"
    if not db_ok:
        status = "error"
    elif any(s.stale_feed for s in stores):
        status = "degraded"
 
    return HealthResponse(
        status=status,
        version=APP_VERSION,
        uptime_seconds=round(now - _start_time, 1),
        stores=stores,
        db_connected=db_ok,
    )
 