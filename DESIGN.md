# DESIGN.md

## Overview

**projectPurple** is an end-to-end offline retail intelligence platform that ingests CCTV footage, runs a CV pipeline (YOLOv8 + ByteTrack + Re-ID) to detect and track visitors, emits structured events, stores them via a FastAPI backend, and visualises live metrics on a React dashboard.

---

## System Architecture

```
+--------------------------------------------------------------+
|                        CCTV Cameras                          |
|         (Entry Cam) (Floor Cam) (Billing Cam)                |
+-------------------+------------------------------------------+
                    |  .mp4 / .avi / .mkv clips
                    v
+--------------------------------------------------------------+
|               pipeline/  (CV Engine)                         |
|  +----------+  +--------------+  +------------------------+ |
|  | YOLOv8n  |->|  ByteTracker |->|  ReIDBank + StaffClf   | |
|  |(detect)  |  |(Kalman+IoU)  |  |  (appearance embed)    | |
|  +----------+  +--------------+  +------------------------+ |
|                        |                                     |
|               emit.py -> events.jsonl  -------------------->|
+--------------------------------------------------------------+
                    |  POST /events/ingest (batches of 500)
                    v
+--------------------------------------------------------------+
|               api/   (FastAPI Backend)                       |
|  +------------+  +----------+  +----------+  +----------+  |
|  | ingestion  |  | metrics  |  |  funnel  |  |anomalies |  |
|  +------------+  +----------+  +----------+  +----------+  |
|                     SQLite (aiosqlite)                       |
|                  [swap -> asyncpg/PostgreSQL]                |
+------------------------------+-------------------------------+
                               |  REST + WebSocket (every 5s)
                               v
+--------------------------------------------------------------+
|             dashboard/  (React + Vite + Tailwind)            |
|   Metrics Grid | Visitor Funnel | Zone Heatmap | Anomalies   |
|                    Live WebSocket feed                        |
+--------------------------------------------------------------+
```

---

## Data Flow

```
1. Place .mp4 clips in clips/STORE_<ID>/
2. Run: cd pipeline && ./run.sh --api http://localhost:8000
3. Pipeline: frame-by-frame YOLO -> ByteTrack -> emit events to API
4. API: ingests events -> SQLite -> serves metrics/funnel/heatmap/anomalies
5. Dashboard: WebSocket receives live metrics every 5s -> React re-renders
```

---

## System Design

### 1. Pipeline - CV Engine

**Files:** `pipeline/detection.py`, `pipeline/tracker.py`, `pipeline/emit.py`

#### detection.py - ClipProcessor

| Concern | Implementation |
|---|---|
| Person detection | YOLOv8 nano (yolov8n.pt), conf >= 0.35, IOU <= 0.45 |
| Multi-object tracking | ByteTracker - high-conf pass (IoU >= 0.5) then low-conf fallback (IoU >= 0.3) |
| Re-identification | ReIDBank - cosine sim >= 0.85 on 96-dim histogram embedding, 5-min window |
| Staff classification | StaffClassifier - HSV uniform colour ratio >= 40% on torso ROI, 3-frame vote |
| Entry/exit | Threshold line at 35% frame height; direction from prev_cy -> curr_cy |
| Zone tracking | Ray-casting polygon containment; dwell emitted every 30s |
| Billing | Queue depth = tracks in BILLING polygon minus 1 |

#### tracker.py - Core Algorithms

- **KalmanBoxTracker** - 4-state constant-velocity model [cx, cy, vx, vy]; observation [cx, cy]
- **ByteTracker** - Simplified ByteTrack; confirmed after MIN_HITS=3 frames; dropped after MAX_AGE=30 frames without match
- **ReIDBank** - Colour histogram Re-ID; cosine similarity; marks visitors as exited and re-matches on re-entry
- **StaffClassifier** - Configurable HSV range (default: dark blue + black); torso ROI = middle vertical third of bounding box

#### Event Types Emitted

| Event | Trigger |
|---|---|
| ENTRY | Track crosses entry line upward |
| EXIT | Track crosses entry line downward |
| ZONE_ENTER | Track centroid enters zone polygon |
| ZONE_EXIT | Track centroid leaves zone polygon |
| ZONE_DWELL | Every 30 seconds while inside a zone |
| BILLING_QUEUE_JOIN | Track enters BILLING zone when queue depth > 0 |
| BILLING_ABANDON | Track leaves BILLING zone without purchase |
| RE_ENTRY | ReIDBank matches a previously-exited visitor |

---

### 2. API - FastAPI Backend

**Files:** `api/app/`

| Module | Responsibility |
|---|---|
| main.py | FastAPI app, CORS, JSON structured logging, global exception handler, WebSocket live feed |
| database.py | aiosqlite schema init, POS CSV loader, connection pool |
| ingestion.py | Batch ingest (up to 500 events); idempotent by event_id |
| metrics.py | Footfall count, avg dwell time, staff ratio, conversion rate from POS join |
| funnel.py | Entry -> zone -> billing -> purchase funnel; zone visit heatmap aggregation |
| anomalies.py | Statistical anomaly detection (Z-score / threshold based) |
| health.py | /health - DB ping + uptime |
| models.py | Pydantic v2 models for all request/response contracts |

**WebSocket:** `/ws/live/{store_id}` pushes metrics_update JSON every 5 seconds to all connected dashboard clients.

#### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | / | API info and route listing |
| GET | /health | Health check + DB ping |
| POST | /events/ingest | Ingest batch of <=500 events (207 Multi-Status) |
| GET | /stores/{store_id}/metrics | KPIs: footfall, dwell, conversion, staff ratio |
| GET | /stores/{store_id}/funnel | Visitor funnel stages |
| GET | /stores/{store_id}/heatmap | Zone visit heatmap data |
| GET | /stores/{store_id}/anomalies | Detected anomalies for the store |
| WS | /ws/live/{store_id} | Live metrics push every 5 seconds |

---

### 3. Dashboard - React Frontend

**Files:** `dashboard/src/`

- Built with **React + Vite + Tailwind CSS**
- Connects to REST API for initial load and WebSocket for live updates
- Components: Header, MetricsGrid, ConsolePanel, and more
- Store selector to switch between STORE_BLR_001, STORE_DEL_002, STORE_MUM_003

---

### 4. Simulation

**File:** `simulation/simulate.py`

Generates synthetic visitor events without needing real video footage. Useful for:
- Testing the API and dashboard end-to-end
- Load testing the ingest pipeline
- Demoing the dashboard with realistic-looking data

---

## Data Schema

The event log follows the `sample_events.jsonl` schema. Each JSONL entry is a JSON object with:

| Field | Type | Description |
|---|---|---|
| event_id | string | Unique identifier for the event (UUID) |
| timestamp | string | ISO 8601 datetime of the event |
| store_id | string | Store identifier (e.g. STORE_BLR_001) |
| camera_id | string | Camera identifier (e.g. CAM_ENTRY_01) |
| visitor_id | string | Persistent visitor identifier |
| event_type | string | One of the defined event types |
| is_staff | boolean | Whether the visitor is classified as staff |
| zone_id | string | Zone identifier (for zone events) |
| dwell_seconds | number | Dwell time in seconds (for dwell events) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Object Detection | YOLOv8 nano (ultralytics) |
| Multi-Object Tracking | ByteTrack (custom, scipy Hungarian matching + Kalman filter) |
| Re-Identification | Colour histogram cosine similarity (drop-in for OSNet/torchreid) |
| Video Processing | OpenCV (cv2) |
| Backend API | FastAPI + uvicorn |
| Database | SQLite via aiosqlite (production: PostgreSQL via asyncpg) |
| Data Validation | Pydantic v2 |
| Frontend | React + Vite + Tailwind CSS |
| Realtime | WebSocket (FastAPI native) |
| Containerisation | Docker + Docker Compose |
| HTTP Client | httpx (pipeline -> API streaming) |

---

## AI-Assisted Decisions

- **Model Selection**: Chosen model and reasoning.
- **Prompt Engineering**: Key prompts and why they were used.
- **Tooling**: Any automation or auxiliary tools employed.
- **Evaluation Strategies**: How AI-generated components were validated.

---

## Testing & Validation

- Unit tests and integration tests for each module.
- Validation of `event_log.jsonl` against the provided `sample_events.jsonl` schema.
- End-to-end tests using `simulation/simulate.py` to verify the full data flow.
- API correctness verified via Swagger UI at http://localhost:8000/docs.
