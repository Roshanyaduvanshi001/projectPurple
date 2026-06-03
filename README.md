# 🟣 projectPurple — Store Intelligence Platform

> **Real-time offline retail analytics powered by CCTV computer vision, multi-object tracking, and a live React dashboard.**

---

## 📌 Table of Contents

- [Project Overview](#-project-overview)
- [Video Clip Requirements](#-video-clip-requirements-for-the-clips-folder)
- [System Architecture](#-system-architecture)
- [Folder Structure](#-folder-structure)
- [Component Design](#-component-design)
  - [Pipeline (CV Engine)](#1-pipeline--cv-engine)
  - [API (FastAPI Backend)](#2-api--fastapi-backend)
  - [Dashboard (React Frontend)](#3-dashboard--react-frontend)
  - [Simulation](#4-simulation)
- [Data Flow](#-data-flow)
- [Store Layout Configuration](#-store-layout-configuration)
- [API Reference](#-api-reference)
- [Setup & Running](#-setup--running)
  - [Prerequisites](#prerequisites)
  - [One-Time Setup](#one-time-setup)
  - [Option A — Docker](#option-a--docker-recommended)
  - [Option B — Local Dev](#option-b--local-dev-hot-reload)
  - [Option C — Real CCTV Pipeline](#option-c--real-cctv-pipeline)
  - [Utility Commands](#utility-commands)
  - [run.sh Reference](#runsh-complete-reference)
- [Environment Variables](#-environment-variables)
- [Tech Stack](#-tech-stack)

---

## 📖 Project Overview

**projectPurple** is an end-to-end offline retail intelligence system that:

1. **Ingests CCTV footage** from multiple cameras (entry, floor, billing) across multiple store locations.
2. **Runs a CV pipeline** (YOLOv8 + ByteTrack + Re-ID) to detect people, assign persistent visitor IDs, classify staff vs. customers, and track movement through store zones.
3. **Emits structured events** (`ENTRY`, `EXIT`, `ZONE_ENTER`, `ZONE_EXIT`, `ZONE_DWELL`, `BILLING_*`, `RE_ENTRY`) per visitor per frame.
4. **Ingests those events into a FastAPI backend** backed by SQLite (swap-able with PostgreSQL for production).
5. **Serves a live React dashboard** with real-time metrics, visitor funnel, heatmap, and anomaly detection — pushed via WebSocket every 5 seconds.

---

## 🎥 Video Clip Requirements for the `/clips` Folder

The pipeline expects CCTV footage organised by **store → camera type**. Here is exactly what clips to provide:

### Folder Convention

```
clips/
└── STORE_<CITY>_<NUM>/          # e.g. STORE_BLR_001, STORE_DEL_002, STORE_MUM_003
    ├── entry.mp4                 # → mapped to CAM_ENTRY_01
    ├── floor.mp4                 # → mapped to CAM_FLOOR_01
    └── billing.mp4               # → mapped to CAM_BILLING_01
```

> You can also encode a date in the filename (e.g. `entry_2026-03-03.mp4`) and the pipeline will auto-parse the clip start timestamp.

### Required Camera Views

| Filename pattern | Camera ID auto-assigned | Purpose |
|---|---|---|
| `*entry*` / `*ENTRY*` | `CAM_ENTRY_01` | **Entry/Exit gate** — people cross a threshold line; entry/exit events fired |
| `*floor*` / `*FLOOR*` | `CAM_FLOOR_01` | **Shop floor** — zone dwell tracking (Skincare, Haircare, Pharmacy) |
| `*billing*` / `*BILLING*` | `CAM_BILLING_01` | **Billing counter** — queue depth, billing enter/abandon events |

### Technical Specifications

| Property | Requirement |
|---|---|
| **Format** | `.mp4`, `.avi`, or `.mkv` |
| **Resolution** | **1080p (1920×1080)** recommended; minimum 720p |
| **Frame rate** | **15–30 fps** (YOLOv8 nano tuned for 15 fps) |
| **Camera angle** | Top-down or slight high angle — people must be fully visible |
| **Entry cam angle** | Fixed overhead at the doorway; people walk toward / away from camera |
| **Floor cam angle** | Wide-angle covering the entire zone polygon area |
| **Billing cam angle** | Side or overhead view of counter + queue area |
| **Lighting** | Well-lit retail environment; avoid heavy backlight at entry |
| **Length** | Any duration; tested with 1–2 hour clips |

### What the Pipeline Detects from the Clips

- 👤 **Person detection** — YOLOv8 nano, COCO class 0
- 🏷️ **Staff classification** — HSV colour histogram on torso ROI (detects dark blue/black uniforms by default; configurable in `tracker.py`)
- 🔄 **Re-identification** — cosine similarity on 96-dim colour histogram embedding; recognises returning visitors within 5-minute window
- 📍 **Zone tracking** — ray-casting point-in-polygon against zones from `store_layout.json`
- 🛒 **Billing queue depth** — counts tracks simultaneously in the `BILLING` zone polygon

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        CCTV Cameras                          │
│         (Entry Cam) (Floor Cam) (Billing Cam)                │
└───────────────────┬──────────────────────────────────────────┘
                    │  .mp4 / .avi / .mkv clips
                    ▼
┌──────────────────────────────────────────────────────────────┐
│               pipeline/  (CV Engine)                         │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ YOLOv8n  │→ │  ByteTracker │→ │  ReIDBank + StaffClf   │ │
│  │(detect)  │  │(Kalman+IoU)  │  │  (appearance embed)    │ │
│  └──────────┘  └──────────────┘  └────────────────────────┘ │
│                        │                                     │
│               emit.py → events.jsonl  ──────────────────────►│
└──────────────────────────────────────────────────────────────┘
                    │  POST /events/ingest (batches of 500)
                    ▼
┌──────────────────────────────────────────────────────────────┐
│               api/   (FastAPI Backend)                       │
│  ┌────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ ingestion  │  │ metrics  │  │  funnel  │  │anomalies │  │
│  └────────────┘  └──────────┘  └──────────┘  └──────────┘  │
│                     SQLite (aiosqlite)                       │
│                  [swap → asyncpg/PostgreSQL]                 │
└──────────────────────────────┬───────────────────────────────┘
                               │  REST + WebSocket (every 5s)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│             dashboard/  (React + Vite + Tailwind)            │
│   Metrics Grid │ Visitor Funnel │ Zone Heatmap │ Anomalies   │
│                    Live WebSocket feed                        │
└──────────────────────────────────────────────────────────────┘
```

---

## 📁 Folder Structure

```
projectPurple/
│
├── clips/                          # 📹 CCTV video input (place your clips here)
│   └── STORE_<ID>/
│       ├── entry.mp4
│       ├── floor.mp4
│       └── billing.mp4
│
├── pipeline/                       # 🧠 Computer Vision engine
│   ├── detection.py                # Main orchestrator: YOLO → track → events
│   ├── tracker.py                  # ByteTracker, ReIDBank, StaffClassifier
│   ├── emit.py                     # Event emitter (JSONL file or HTTP stream)
│   ├── run.sh                      # Batch runner: all clips → all stores
│   └── requirements.txt
│
├── api/                            # ⚡ FastAPI backend
│   ├── Dockerfile.api
│   ├── requirements.txt
│   └── app/
│       ├── main.py                 # FastAPI app, routes, WS, middleware
│       ├── database.py             # aiosqlite init, schema, POS CSV loader
│       ├── ingestion.py            # Batch event ingest (idempotent by event_id)
│       ├── metrics.py              # Store-level KPIs (footfall, dwell, conversion)
│       ├── funnel.py               # Visitor funnel + zone heatmap aggregation
│       ├── anomalies.py            # Statistical anomaly detection
│       ├── health.py               # /health endpoint
│       └── models.py               # Pydantic request/response models
│
├── dashboard/                      # 🖥️ React live dashboard
│   ├── src/
│   │   ├── App.jsx                 # Root: store selector, WS connection, layout
│   │   ├── api.js                  # REST helper functions
│   │   ├── index.css               # Global styles (Tailwind base)
│   │   ├── main.jsx                # Vite entry point
│   │   └── components/
│   │       ├── Header.jsx
│   │       ├── MetricsGrid.jsx
│   │       ├── ConsolePanel.jsx
│   │       └── ...
│   ├── tailwind.config.js
│   ├── .env                        # VITE_API_URL, VITE_WS_URL
│   └── Dockerfile.dashboard
│
├── simulation/
│   └── simulate.py                 # Synthetic event generator (no real clips needed)
│
├── store_layout.json               # 🗺️ Zone polygon definitions per store/camera
├── pos_transactions.csv            # 💳 POS sales data (for conversion calculation)
├── docker-compose.yml              # 🐳 Full stack: api + dashboard
└── README.md
```

---

## 🔧 Component Design

### 1. Pipeline — CV Engine

**Files:** `pipeline/detection.py`, `pipeline/tracker.py`, `pipeline/emit.py`

#### detection.py — `ClipProcessor`

| Concern | Implementation |
|---|---|
| Person detection | YOLOv8 nano (`yolov8n.pt`), conf ≥ 0.35, IOU ≤ 0.45 |
| Multi-object tracking | `ByteTracker` — high-conf pass (IoU ≥ 0.5) then low-conf fallback (IoU ≥ 0.3) |
| Re-identification | `ReIDBank` — cosine sim ≥ 0.85 on 96-dim histogram embedding, 5-min window |
| Staff classification | `StaffClassifier` — HSV uniform colour ratio ≥ 40% on torso ROI, 3-frame vote |
| Entry/exit | Threshold line at 35% frame height; direction from `prev_cy` → `curr_cy` |
| Zone tracking | Ray-casting polygon containment; dwell emitted every 30s |
| Billing | Queue depth = tracks in `BILLING` polygon − 1 |

#### tracker.py — Core Algorithms

- **`KalmanBoxTracker`** — 4-state constant-velocity model `[cx, cy, vx, vy]`; observation `[cx, cy]`
- **`ByteTracker`** — Simplified ByteTrack; confirmed after `MIN_HITS=3` frames; dropped after `MAX_AGE=30` frames without match
- **`ReIDBank`** — Colour histogram Re-ID; cosine similarity; marks visitors as exited and re-matches on re-entry
- **`StaffClassifier`** — Configurable HSV range (default: dark blue + black); torso ROI = middle vertical third of bounding box

#### Event Types Emitted

| Event | Trigger |
|---|---|
| `ENTRY` | Track crosses entry line upward |
| `EXIT` | Track crosses entry line downward |
| `ZONE_ENTER` | Track centroid enters zone polygon |
| `ZONE_EXIT` | Track centroid leaves zone polygon |
| `ZONE_DWELL` | Every 30 seconds while inside a zone |
| `BILLING_QUEUE_JOIN` | Track enters BILLING zone when queue depth > 0 |
| `BILLING_ABANDON` | Track leaves BILLING zone without purchase |
| `RE_ENTRY` | ReIDBank matches a previously-exited visitor |

---

### 2. API — FastAPI Backend

**Files:** `api/app/`

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app, CORS, JSON structured logging, global exception handler, WebSocket live feed |
| `database.py` | aiosqlite schema init, POS CSV loader, connection pool |
| `ingestion.py` | Batch ingest (up to 500 events); idempotent by `event_id` |
| `metrics.py` | Footfall count, avg dwell time, staff ratio, conversion rate from POS join |
| `funnel.py` | Entry → zone → billing → purchase funnel; zone visit heatmap aggregation |
| `anomalies.py` | Statistical anomaly detection (Z-score / threshold based) |
| `health.py` | `/health` — DB ping + uptime |
| `models.py` | Pydantic v2 models for all request/response contracts |

**WebSocket:** `/ws/live/{store_id}` pushes `metrics_update` JSON every 5 seconds to all connected dashboard clients.

---

### 3. Dashboard — React Frontend

**Files:** `dashboard/src/`

- Built with **React + Vite + Tailwind CSS**
- Connects to REST API for initial load and WebSocket for live updates
- Components: `Header`, `MetricsGrid`, `ConsolePanel`, and more
- Store selector to switch between `STORE_BLR_001`, `STORE_DEL_002`, `STORE_MUM_003`

---

### 4. Simulation

**File:** `simulation/simulate.py`

Generates synthetic visitor events without needing real video footage. Useful for:
- Testing the API and dashboard end-to-end
- Load testing the ingest pipeline
- Demoing the dashboard with realistic-looking data

---

## 🔄 Data Flow

```
1. Place .mp4 clips in clips/STORE_<ID>/
2. Run: cd pipeline && ./run.sh --api http://localhost:8000
3. Pipeline: frame-by-frame YOLO → ByteTrack → emit events to API
4. API: ingests events → SQLite → serves metrics/funnel/heatmap/anomalies
5. Dashboard: WebSocket receives live metrics every 5s → React re-renders
```

---

## 🗺️ Store Layout Configuration

`store_layout.json` defines camera zones as polygons in pixel coordinates (1920×1080 frame space):

```json
{
  "stores": [
    {
      "store_id": "STORE_BLR_001",
      "zones": [
        {
          "zone_id": "SKINCARE",
          "cameras": ["CAM_FLOOR_01"],
          "polygon": [[100,100],[600,100],[600,900],[100,900]]
        },
        {
          "zone_id": "BILLING",
          "cameras": ["CAM_BILLING_01"],
          "polygon": [[100,100],[1820,100],[1820,980],[100,980]]
        }
      ]
    }
  ]
}
```

**Supported Zones:** `SKINCARE`, `HAIRCARE`, `PHARMACY`, `BILLING`

> Zone polygons must match the coordinate space of the camera resolution. Adjust for non-1080p clips.

---

## 🌐 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API info and route listing |
| `GET` | `/health` | Health check + DB ping |
| `POST` | `/events/ingest` | Ingest batch of ≤500 events (207 Multi-Status) |
| `GET` | `/stores/{store_id}/metrics` | KPIs: footfall, dwell, conversion, staff ratio |
| `GET` | `/stores/{store_id}/funnel` | Visitor funnel stages |
| `GET` | `/stores/{store_id}/heatmap` | Zone visit heatmap data |
| `GET` | `/stores/{store_id}/anomalies` | Detected anomalies for the store |
| `WS` | `/ws/live/{store_id}` | Live metrics push every 5 seconds |

Swagger UI available at: `http://localhost:8000/docs`

---

## 🧪 API Verification Walkthrough

We verified all core endpoints of the Store Intelligence API using a browser agent navigating the live Swagger interactive UI at http://localhost:8000/docs.

### Verification Results

| Endpoint | Method | Parameters Tested | Expected Status | Actual Status | Response Snippet |
|---|---|---|---|---|---|
| `/health` | GET | None | `200 OK` | `200 OK` | `{"status": "ok", "version": "1.0.0"}` |
| `/stores/{store_id}/metrics` | GET | `store_id = STORE_BLR_001` | `200 OK` | `200 OK` | `{"store_id": "STORE_BLR_001", "unique_visitors": 7, "conversion_rate": 0}` |
| `/stores/{store_id}/funnel` | GET | `store_id = STORE_BLR_001` | `200 OK` | `200 OK` | `{"store_id": "STORE_BLR_001", "stages": [{"stage": "Entry", "count": 20}, ...]}` |
| `/stores/{store_id}/heatmap` | GET | `store_id = STORE_BLR_001` | `200 OK` | `200 OK` | `{"store_id": "STORE_BLR_001", "zones": [...]}` |
| `/stores/{store_id}/anomalies` | GET | `store_id = STORE_BLR_001` | `200 OK` | `200 OK` | `{"store_id": "STORE_BLR_001", "anomalies": [...]}` |

All tested endpoints are operational and returned successful responses.

### Video Recording of Verification

Below is a recording showing the browser subagent expanding the endpoints, entering parameters, and executing requests:

![API Docs Verification Video](file:///C:/Users/rosha/.gemini/antigravity-ide/brain/952eac7c-a105-4f34-9b87-019031404095/check_api_docs_1780503709393.webp)

---

## 🚀 Setup & Running

### Prerequisites

- Python 3.10+
- Node.js 18+
- Docker + Docker Compose (for containerised run)

### Option A — Docker Compose (Recommended)

```bash
# 1. Place your clips:
mkdir -p clips/STORE_BLR_001
cp your_entry_cam.mp4 clips/STORE_BLR_001/entry.mp4
cp your_floor_cam.mp4 clips/STORE_BLR_001/floor.mp4
cp your_billing_cam.mp4 clips/STORE_BLR_001/billing.mp4

# 2. Start API + Dashboard
docker-compose up --build

# 3. Run CV pipeline (separate terminal, needs GPU/CPU with ultralytics)
cd pipeline
pip install -r requirements.txt
./run.sh --api http://localhost:8000

# 4. Open dashboard
# http://localhost:3000
```

### Option B — Local Dev

```bash
# API
cd api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Dashboard
cd dashboard
npm install
npm run dev    # http://localhost:5173

# Pipeline (after API is running)
cd pipeline
pip install -r requirements.txt
./run.sh --api http://localhost:8000

# Or simulate without real clips:
cd simulation
python simulate.py --api http://localhost:8000 --stores STORE_BLR_001
```

---

## 🔑 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/store_intelligence.db` | SQLite database path |
| `POS_CSV_PATH` | `/data/pos_transactions.csv` | POS transactions CSV |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CLIPS_DIR` | `../clips` | Clips root for `run.sh` |
| `OUTPUT_DIR` | `../output/events` | JSONL output directory |
| `API_URL` | _(empty)_ | If set, pipeline streams events to API in real-time |
| `STORE_FILTER` | _(empty)_ | If set, process only this store ID |
| `VITE_API_URL` | `http://localhost:8000` | Dashboard → API base URL |
| `VITE_WS_URL` | `ws://localhost:8000` | Dashboard → WebSocket base URL |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Object Detection** | YOLOv8 nano (`ultralytics`) |
| **Multi-Object Tracking** | ByteTrack (custom, `scipy` Hungarian matching + Kalman filter) |
| **Re-Identification** | Colour histogram cosine similarity (drop-in for OSNet/torchreid) |
| **Video Processing** | OpenCV (`cv2`) |
| **Backend API** | FastAPI + uvicorn |
| **Database** | SQLite via `aiosqlite` (production: PostgreSQL via `asyncpg`) |
| **Data Validation** | Pydantic v2 |
| **Frontend** | React + Vite + Tailwind CSS |
| **Realtime** | WebSocket (FastAPI native) |
| **Containerisation** | Docker + Docker Compose |
| **HTTP Client** | `httpx` (pipeline → API streaming) |
