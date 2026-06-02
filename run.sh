#!/usr/bin/env bash
# =============================================================================
# projectPurple — Master Run Script
# =============================================================================
# Usage:
#   ./run.sh docker          → Full stack via Docker Compose (API + Dashboard)
#   ./run.sh api             → Run FastAPI backend locally (port 8000)
#   ./run.sh dashboard       → Run React dashboard locally (port 5173)
#   ./run.sh pipeline        → Run CV pipeline on clips/ folder
#   ./run.sh simulate        → Generate synthetic events (no clips needed)
#   ./run.sh all             → Local: API + Dashboard + Simulation in parallel
#   ./run.sh stop            → Stop all Docker containers
#   ./run.sh logs            → Tail Docker logs (api + dashboard)
#   ./run.sh status          → Show running services
#   ./run.sh clean           → Remove Docker volumes + build cache
# =============================================================================

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT_DIR/api"
DASHBOARD_DIR="$ROOT_DIR/dashboard"
PIPELINE_DIR="$ROOT_DIR/pipeline"
SIMULATION_DIR="$ROOT_DIR/simulation"
CLIPS_DIR="$ROOT_DIR/clips"

log()     { echo -e "${CYAN}[$(date +%H:%M:%S)]${RESET} $*"; }
success() { echo -e "${GREEN}✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $*"; }
error()   { echo -e "${RED}✗ ERROR:${RESET} $*"; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}═══ $* ═══${RESET}\n"; }

# ── Dependency checks ─────────────────────────────────────────────────────────
check_docker()  { command -v docker  &>/dev/null || error "Docker not found. Install from https://docker.com"; }
check_python()  {
    command -v python3 &>/dev/null && return
    command -v python  &>/dev/null && return
    command -v py      &>/dev/null && return
    error "Python 3 not found. Install from https://python.org"
}
check_node()    { command -v node &>/dev/null || error "Node.js not found. Install from https://nodejs.org"; }
check_npm()     { command -v npm  &>/dev/null || error "npm not found. Install Node.js from https://nodejs.org"; }

# Resolve the correct python binary
PYTHON() {
    if command -v python3 &>/dev/null; then python3 "$@"
    elif command -v python &>/dev/null; then python "$@"
    else py "$@"; fi
}

# Activate venv cross-platform (Windows Git Bash uses Scripts/, Unix uses bin/)
venv_activate() {
    local dir="$1"
    if [ -f "$dir/Scripts/activate" ]; then
        # shellcheck disable=SC1091
        source "$dir/Scripts/activate"
    elif [ -f "$dir/bin/activate" ]; then
        # shellcheck disable=SC1091
        source "$dir/bin/activate"
    else
        error "Cannot find activate script in $dir"
    fi
}

# =============================================================================
# MODE: docker
# =============================================================================
run_docker() {
    header "Starting Full Stack via Docker Compose"
    check_docker

    # Ensure clips folder exists
    mkdir -p "$CLIPS_DIR"

    # Create store subdirs for sample layout
    for store in STORE_BLR_001 STORE_DEL_002 STORE_MUM_003 STORE_HYD_004 STORE_CHN_005; do
        mkdir -p "$CLIPS_DIR/$store"
    done

    log "Building and starting containers..."
    docker compose -f "$ROOT_DIR/docker-compose.yml" up --build -d

    log "Waiting for API to be healthy..."
    local retries=0
    until curl -sf http://localhost:8000/health &>/dev/null || [ $retries -ge 20 ]; do
        retries=$((retries + 1))
        echo -n "."
        sleep 2
    done
    echo ""

    if curl -sf http://localhost:8000/health &>/dev/null; then
        success "API is healthy at ${BOLD}http://localhost:8000${RESET}"
        success "Swagger docs at  ${BOLD}http://localhost:8000/docs${RESET}"
        success "Dashboard at     ${BOLD}http://localhost:3000${RESET}"
        echo ""
        log "Run ${BOLD}./run.sh logs${RESET} to tail logs"
        log "Run ${BOLD}./run.sh simulate${RESET} to populate with synthetic data"
        log "Run ${BOLD}./run.sh stop${RESET}    to shut down"
    else
        warn "API may not be ready yet. Check logs with: ./run.sh logs"
    fi
}

# =============================================================================
# MODE: api  (local dev)
# =============================================================================
run_api() {
    header "Starting FastAPI Backend (local)"
    check_python

    cd "$API_DIR"

    # Create venv if not exists
    if [ ! -d ".venv" ]; then
        log "Creating Python virtual environment..."
        PYTHON -m venv .venv
    fi

    # Activate (cross-platform)
    venv_activate .venv
    log "Installing API dependencies..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt

    # Set env vars
    export DB_PATH="${DB_PATH:-$API_DIR/store_intelligence.db}"
    export POS_CSV_PATH="${POS_CSV_PATH:-$ROOT_DIR/pos_transactions.csv}"
    export LOG_LEVEL="${LOG_LEVEL:-INFO}"

    log "Starting uvicorn on http://localhost:8000 ..."
    success "Swagger UI → http://localhost:8000/docs"
    success "WebSocket  → ws://localhost:8000/ws/live/{store_id}"
    echo ""

    uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --reload \
        --log-config /dev/null
}

# =============================================================================
# MODE: dashboard  (local dev)
# =============================================================================
run_dashboard() {
    header "Starting React Dashboard (local)"
    check_node
    check_npm

    cd "$DASHBOARD_DIR"

    # Ensure .env exists
    if [ ! -f ".env" ]; then
        log "Creating .env for dashboard..."
        echo "VITE_API_URL=http://localhost:8000" > .env
        echo "VITE_WS_URL=ws://localhost:8000"   >> .env
    fi

    log "Installing npm packages..."
    npm install --silent

    log "Starting Vite dev server on http://localhost:5173 ..."
    echo ""
    npm run dev
}

# =============================================================================
# MODE: pipeline  (process real clips)
# =============================================================================
run_pipeline() {
    header "Running CV Pipeline on clips/"
    check_python

    cd "$PIPELINE_DIR"

    if [ ! -d ".venv" ]; then
        log "Creating Python virtual environment..."
        PYTHON -m venv .venv
    fi

    venv_activate .venv
    log "Installing pipeline dependencies (this may take a while — ultralytics + torch)..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt

    # Check clips exist
    if [ -z "$(ls -A "$CLIPS_DIR" 2>/dev/null)" ]; then
        warn "clips/ directory is empty!"
        warn "Place video files like:"
        warn "  clips/STORE_BLR_001/entry.mp4"
        warn "  clips/STORE_BLR_001/floor.mp4"
        warn "  clips/STORE_BLR_001/billing.mp4"
        warn ""
        warn "Then re-run: ./run.sh pipeline"
        warn "Or use synthetic data: ./run.sh simulate"
        exit 1
    fi

    API_URL="${API_URL:-}"
    API_FLAG=""
    if [ -n "$API_URL" ]; then
        API_FLAG="--api $API_URL"
        log "Will stream events to API: $API_URL"
    else
        log "No API_URL set — events will be written to output/events/*.jsonl"
        log "To stream to API: API_URL=http://localhost:8000 ./run.sh pipeline"
    fi

    log "Starting pipeline..."
    CLIPS_DIR="$CLIPS_DIR" \
    LAYOUT="$ROOT_DIR/store_layout.json" \
    OUTPUT_DIR="$ROOT_DIR/output/events" \
        bash "$PIPELINE_DIR/run.sh" $API_FLAG

    success "Pipeline complete. Events in $ROOT_DIR/output/events/"
}

# =============================================================================
# MODE: simulate  (synthetic events, no clips needed)
# =============================================================================
run_simulate() {
    header "Running Simulation (Synthetic Events)"
    check_python

    # Check API is reachable
    if ! curl -sf http://localhost:8000/health &>/dev/null; then
        warn "API is not running at http://localhost:8000"
        warn "Start it first: ./run.sh api   (local)"
        warn "          or:   ./run.sh docker (Docker)"
        exit 1
    fi

    cd "$SIMULATION_DIR"

    if [ ! -d ".venv" ]; then
        log "Creating Python virtual environment..."
        PYTHON -m venv .venv
    fi

    venv_activate .venv
    pip install -q --upgrade pip
    pip install -q httpx pydantic

    log "Simulating events for all 5 stores → http://localhost:8000 ..."
    echo ""

    PYTHON simulate.py \
        --api  http://localhost:8000 \
        --stores STORE_BLR_001 STORE_DEL_002 STORE_MUM_003 STORE_HYD_004 STORE_CHN_005

    success "Simulation complete. Refresh your dashboard!"
}

# =============================================================================
# MODE: all  (local: API + Dashboard + Simulate)
# =============================================================================
run_all() {
    header "Starting Full Stack Locally"
    check_python
    check_node

    log "Starting API in background..."
    bash "$ROOT_DIR/run.sh" api &
    API_PID=$!

    log "Waiting for API to start..."
    local retries=0
    until curl -sf http://localhost:8000/health &>/dev/null || [ $retries -ge 25 ]; do
        retries=$((retries + 1))
        sleep 2
        echo -n "."
    done
    echo ""
    success "API ready at http://localhost:8000"

    log "Starting dashboard in background..."
    bash "$ROOT_DIR/run.sh" dashboard &
    DASH_PID=$!

    log "Waiting for dashboard to start (5s)..."
    sleep 5

    log "Running simulation to populate data..."
    bash "$ROOT_DIR/run.sh" simulate || warn "Simulation failed — API may still be warming up"

    echo ""
    success "Stack is running!"
    success "  API:       http://localhost:8000"
    success "  Swagger:   http://localhost:8000/docs"
    success "  Dashboard: http://localhost:5173"
    echo ""
    log "Press Ctrl+C to stop all services"

    # Wait for background processes
    wait $API_PID $DASH_PID
}

# =============================================================================
# MODE: stop
# =============================================================================
run_stop() {
    header "Stopping Docker Services"
    check_docker
    docker compose -f "$ROOT_DIR/docker-compose.yml" down
    success "All containers stopped"
}

# =============================================================================
# MODE: logs
# =============================================================================
run_logs() {
    header "Tailing Docker Logs"
    check_docker
    docker compose -f "$ROOT_DIR/docker-compose.yml" logs -f --tail=50
}

# =============================================================================
# MODE: status
# =============================================================================
run_status() {
    header "Service Status"

    echo -e "${BOLD}Docker containers:${RESET}"
    check_docker && docker compose -f "$ROOT_DIR/docker-compose.yml" ps 2>/dev/null || warn "Docker not running"

    echo ""
    echo -e "${BOLD}API health:${RESET}"
    if curl -sf http://localhost:8000/health | python3 -m json.tool 2>/dev/null; then
        success "API is UP"
    else
        warn "API is not responding on port 8000"
    fi

    echo ""
    echo -e "${BOLD}Dashboard:${RESET}"
    if curl -sf http://localhost:3000 &>/dev/null || curl -sf http://localhost:5173 &>/dev/null; then
        success "Dashboard is UP"
    else
        warn "Dashboard not responding on port 3000 or 5173"
    fi
}

# =============================================================================
# MODE: clean
# =============================================================================
run_clean() {
    header "Cleaning Docker Volumes and Cache"
    check_docker
    warn "This will delete all stored event data in Docker volumes!"
    read -rp "Are you sure? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        docker compose -f "$ROOT_DIR/docker-compose.yml" down -v --remove-orphans
        docker builder prune -f
        success "Clean complete"
    else
        log "Aborted"
    fi
}

# =============================================================================
# Help
# =============================================================================
show_help() {
    echo -e "
${BOLD}${CYAN}projectPurple — Store Intelligence Platform${RESET}

${BOLD}Usage:${RESET}
  ./run.sh <mode>

${BOLD}Modes:${RESET}
  ${GREEN}docker${RESET}      Full stack via Docker Compose (API port 8000, Dashboard port 3000)
  ${GREEN}api${RESET}         FastAPI backend only, local dev with hot-reload (port 8000)
  ${GREEN}dashboard${RESET}   React dashboard only, local dev (port 5173)
  ${GREEN}pipeline${RESET}    Run YOLOv8 CV pipeline on clips/ folder
  ${GREEN}simulate${RESET}    Generate synthetic visitor events (API must be running)
  ${GREEN}all${RESET}         Start API + Dashboard + Simulation locally in parallel
  ${GREEN}stop${RESET}        Stop Docker containers
  ${GREEN}logs${RESET}        Tail Docker Compose logs
  ${GREEN}status${RESET}      Check running services and API health
  ${GREEN}clean${RESET}       Remove Docker volumes and build cache (DATA LOSS WARNING)

${BOLD}Quick Start (Docker):${RESET}
  ./run.sh docker
  ./run.sh simulate        # populate with data
  open http://localhost:3000

${BOLD}Quick Start (Local):${RESET}
  # Terminal 1
  ./run.sh api
  # Terminal 2
  ./run.sh dashboard
  # Terminal 3
  ./run.sh simulate

${BOLD}Pipeline with real CCTV clips:${RESET}
  # Place clips:
  mkdir -p clips/STORE_BLR_001
  cp /path/to/entry_cam.mp4   clips/STORE_BLR_001/entry.mp4
  cp /path/to/floor_cam.mp4   clips/STORE_BLR_001/floor.mp4
  cp /path/to/billing_cam.mp4 clips/STORE_BLR_001/billing.mp4

  # Run pipeline (streams events to running API):
  API_URL=http://localhost:8000 ./run.sh pipeline

${BOLD}Environment variables:${RESET}
  API_URL       URL to stream events to (pipeline mode)
  DB_PATH       SQLite DB path (api mode, default: api/store_intelligence.db)
  POS_CSV_PATH  POS CSV path  (api mode, default: pos_transactions.csv)
  STORE_FILTER  Process only one store in pipeline mode
"
}

# =============================================================================
# Entry point
# =============================================================================
MODE="${1:-help}"

case "$MODE" in
    docker)    run_docker    ;;
    api)       run_api       ;;
    dashboard) run_dashboard ;;
    pipeline)  run_pipeline  ;;
    simulate)  run_simulate  ;;
    all)       run_all       ;;
    stop)      run_stop      ;;
    logs)      run_logs      ;;
    status)    run_status    ;;
    clean)     run_clean     ;;
    help|--help|-h) show_help ;;
    *) error "Unknown mode: '$MODE'. Run ./run.sh help for usage." ;;
esac
