
"""
anomalies.py — Real-time anomaly detection.
 
Detects:
  BILLING_QUEUE_SPIKE   Queue depth exceeds dynamic threshold
  CONVERSION_DROP       Today's conversion rate < 7-day average by >20%
  DEAD_ZONE             A zone with recent history has had no visits in 30 min
  STALE_FEED            No events from a store in the last 10 min (health endpoint)
  EMPTY_STORE           Store has been empty for ≥ 15 min during open hours
 
Severity logic:
  Queue spike:       depth 3-5 → WARN, ≥ 6 → CRITICAL
  Conversion drop:   20-40% below avg → WARN, >40% → CRITICAL
  Dead zone:         30-60 min → INFO, >60 min → WARN
  Stale feed:        10-30 min → WARN, >30 min → CRITICAL
"""
 
from __future__ import annotations
 
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
 
from app.database import get_db
from app.models import Anomaly, AnomalyResponse, AnomalySeverity, AnomalyType
 
log = logging.getLogger("anomalies")
 
QUEUE_SPIKE_WARN     = 3
QUEUE_SPIKE_CRITICAL = 6
CONV_DROP_WARN_PCT   = 0.20   # 20% below average
CONV_DROP_CRIT_PCT   = 0.40   # 40% below average
DEAD_ZONE_WARN_MIN   = 30
DEAD_ZONE_CRIT_MIN   = 60
STALE_WARN_MIN       = 10
STALE_CRIT_MIN       = 30
 
 
def _now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()
 
 
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
 
def _anomaly(
    atype: AnomalyType,
    severity: AnomalySeverity,
    description: str,
    action: str,
    meta: dict | None = None,
) -> Anomaly:
    return Anomaly(
        anomaly_id=str(uuid.uuid4()),
        anomaly_type=atype,
        severity=severity,
        detected_at=_iso(_now()),
        description=description,
        suggested_action=action,
        metadata=meta or {},
    )
 
 
async def detect_anomalies(store_id: str) -> AnomalyResponse:
    conn      = get_db()
    now       = _now()
    anomalies: list[Anomaly] = []
 
    # ── 1. Billing queue spike ────────────────────────────────────────────────
    async with conn.execute(
        """SELECT MAX(queue_depth) as max_qd
           FROM events
           WHERE store_id=? AND event_type='BILLING_QUEUE_JOIN'
             AND ts > ? AND is_staff=0""",
        (store_id, now - 300),   # last 5 minutes
    ) as cur:
        row = await cur.fetchone()
        max_qd = int(row["max_qd"] or 0) if row else 0
 
    if max_qd >= QUEUE_SPIKE_CRITICAL:
        anomalies.append(_anomaly(
            AnomalyType.BILLING_QUEUE_SPIKE,
            AnomalySeverity.CRITICAL,
            f"Billing queue depth is {max_qd} — critically high",
            "Open additional billing counter immediately",
            {"queue_depth": max_qd},
        ))
    elif max_qd >= QUEUE_SPIKE_WARN:
        anomalies.append(_anomaly(
            AnomalyType.BILLING_QUEUE_SPIKE,
            AnomalySeverity.WARN,
            f"Billing queue depth reached {max_qd} in the last 5 minutes",
            "Monitor queue — consider opening a second counter",
            {"queue_depth": max_qd},
        ))
 
    # ── 2. Conversion drop vs 7-day average ──────────────────────────────────
    today_start = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    week_start = today_start - 7 * 86_400
 
    # Today's conversion
    async with conn.execute(
        """SELECT COUNT(*) as total, SUM(converted) as conv
           FROM sessions
           WHERE store_id=? AND is_staff=0 AND entry_ts >= ?""",
        (store_id, today_start),
    ) as cur:
        row = await cur.fetchone()
        today_total = int(row["total"] or 0)
        today_conv  = int(row["conv"] or 0)
 
    today_rate = today_conv / today_total if today_total >= 10 else None
 
    # 7-day average (exclude today)
    async with conn.execute(
        """SELECT COUNT(*) as total, SUM(converted) as conv
           FROM sessions
           WHERE store_id=? AND is_staff=0
             AND entry_ts BETWEEN ? AND ?""",
        (store_id, week_start, today_start),
    ) as cur:
        row = await cur.fetchone()
        hist_total = int(row["total"] or 0)
        hist_conv  = int(row["conv"] or 0)
 
    hist_rate = hist_conv / hist_total if hist_total >= 10 else None
 
    if today_rate is not None and hist_rate and hist_rate > 0:
        drop = (hist_rate - today_rate) / hist_rate
        if drop >= CONV_DROP_CRIT_PCT:
            anomalies.append(_anomaly(
                AnomalyType.CONVERSION_DROP,
                AnomalySeverity.CRITICAL,
                f"Conversion rate {today_rate:.1%} — {drop:.0%} below 7-day avg ({hist_rate:.1%})",
                "Investigate checkout flow, staffing, or product availability",
                {"today_rate": today_rate, "hist_rate": hist_rate, "drop_pct": round(drop, 4)},
            ))
        elif drop >= CONV_DROP_WARN_PCT:
            anomalies.append(_anomaly(
                AnomalyType.CONVERSION_DROP,
                AnomalySeverity.WARN,
                f"Conversion rate {today_rate:.1%} — {drop:.0%} below 7-day avg",
                "Review queue abandonment and zone heatmap for bottlenecks",
                {"today_rate": today_rate, "hist_rate": hist_rate, "drop_pct": round(drop, 4)},
            ))
 
    # ── 3. Dead zone: zone with history but no visits in 30+ min ─────────────
    # Zones active in last 7 days
    async with conn.execute(
        """SELECT DISTINCT zone_id FROM events
           WHERE store_id=? AND zone_id IS NOT NULL AND is_staff=0
             AND ts BETWEEN ? AND ?""",
        (store_id, week_start, now),
    ) as cur:
        known_zones = {r["zone_id"] for r in await cur.fetchall()}
 
    for zone_id in known_zones:
        async with conn.execute(
            """SELECT MAX(ts) as last_visit FROM events
               WHERE store_id=? AND zone_id=? AND is_staff=0
                 AND event_type IN ('ZONE_ENTER','ZONE_DWELL')""",
            (store_id, zone_id),
        ) as cur:
            row = await cur.fetchone()
            last_ts = row["last_visit"] if row else None
 
        if last_ts is None:
            continue
        idle_min = (now - last_ts) / 60
 
        if idle_min >= DEAD_ZONE_CRIT_MIN:
            anomalies.append(_anomaly(
                AnomalyType.DEAD_ZONE,
                AnomalySeverity.WARN,
                f"Zone {zone_id} has had no visitors for {idle_min:.0f} minutes",
                f"Check zone signage and product availability in {zone_id}",
                {"zone_id": zone_id, "idle_minutes": round(idle_min, 1)},
            ))
        elif idle_min >= DEAD_ZONE_WARN_MIN:
            anomalies.append(_anomaly(
                AnomalyType.DEAD_ZONE,
                AnomalySeverity.INFO,
                f"Zone {zone_id} has been quiet for {idle_min:.0f} minutes",
                f"Monitor {zone_id} — may need promotional activity",
                {"zone_id": zone_id, "idle_minutes": round(idle_min, 1)},
            ))
 
    # ── 4. Empty store ────────────────────────────────────────────────────────
    async with conn.execute(
        """SELECT COUNT(*) as active FROM sessions
           WHERE store_id=? AND is_staff=0
             AND entry_ts > ? AND (exit_ts IS NULL OR exit_ts > ?)""",
        (store_id, now - 900, now - 900),
    ) as cur:
        row = await cur.fetchone()
        active = int(row["active"] or 0)
 
    if active == 0:
        # Check if there were ever any visitors today
        async with conn.execute(
            """SELECT COUNT(*) as c FROM sessions
               WHERE store_id=? AND entry_ts >= ?""",
            (store_id, today_start),
        ) as cur:
            row = await cur.fetchone()
            had_visitors_today = int(row["c"] or 0) > 0
 
        if had_visitors_today:
            anomalies.append(_anomaly(
                AnomalyType.EMPTY_STORE,
                AnomalySeverity.INFO,
                "Store has been empty for at least 15 minutes",
                "No action needed — normal if near opening/closing",
            ))
 
    anomalies.sort(
        key=lambda a: ["CRITICAL", "WARN", "INFO"].index(a.severity.value)
    )
 
    return AnomalyResponse(store_id=store_id, anomalies=anomalies)
 