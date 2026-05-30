
#!/usr/bin/env bash
# run.sh — Process all CCTV clips → emit events → optionally ingest into API
#
# Usage:
#   ./run.sh                          # write events.jsonl, no API upload
#   ./run.sh --api http://localhost:8000   # also stream to running API
#   ./run.sh --store STORE_BLR_002    # process a single store
#
# Requires: Python 3.10+, ultralytics, opencv-python, httpx, scipy, pydantic
 
set -euo pipefail
 
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIPS_DIR="${CLIPS_DIR:-$SCRIPT_DIR/../clips}"
LAYOUT="${LAYOUT:-$SCRIPT_DIR/../store_layout.json}"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/../output/events}"
API_URL="${API_URL:-}"
STORE_FILTER="${STORE_FILTER:-}"
 
mkdir -p "$OUTPUT_DIR"
 
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
 
if [[ ! -d "$CLIPS_DIR" ]]; then
    log "ERROR: clips directory not found at $CLIPS_DIR"
    log "Set CLIPS_DIR env var or place clips in ../clips/"
    exit 1
fi
 
# Camera ID mapping: filename pattern → camera ID
camera_id_for() {
    local fname="$1"
    case "$fname" in
        *entry*|*ENTRY*) echo "CAM_ENTRY_01" ;;
        *floor*|*FLOOR*) echo "CAM_FLOOR_01" ;;
        *billing*|*BILLING*) echo "CAM_BILLING_01" ;;
        *) echo "CAM_UNKNOWN_01" ;;
    esac
}
 
# Clip start timestamp: read from filename if ISO encoded, else use default
clip_start_for() {
    local fname="$1"
    # Try to parse YYYY-MM-DD from filename
    if [[ "$fname" =~ ([0-9]{4}-[0-9]{2}-[0-9]{2}) ]]; then
        echo "${BASH_REMATCH[1]}T09:00:00Z"
    else
        echo "2026-03-03T09:00:00Z"
    fi
}
 
total_events=0
stores_processed=0
 
for store_dir in "$CLIPS_DIR"/STORE_*/; do
    store_id=$(basename "$store_dir")
 
    # Apply store filter if set
    if [[ -n "$STORE_FILTER" && "$store_id" != "$STORE_FILTER" ]]; then
        continue
    fi
 
    log "── Processing store: $store_id"
    store_events=0
 
    for clip in "$store_dir"*.mp4 "$store_dir"*.avi "$store_dir"*.mkv 2>/dev/null; do
        [[ -f "$clip" ]] || continue
 
        fname=$(basename "$clip")
        cam_id=$(camera_id_for "$fname")
        clip_start=$(clip_start_for "$fname")
        output_file="$OUTPUT_DIR/${store_id}_${cam_id}.jsonl"
 
        log "  → $fname ($cam_id) → $output_file"
 
        api_flag=""
        if [[ -n "$API_URL" ]]; then
            api_flag="--api-url $API_URL"
        fi
 
        python3 "$SCRIPT_DIR/detect.py" \
            --video "$clip" \
            --store "$store_id" \
            --camera "$cam_id" \
            --layout "$LAYOUT" \
            --output "$output_file" \
            --clip-start "$clip_start" \
            $api_flag
 
        event_count=$(wc -l < "$output_file" 2>/dev/null || echo 0)
        store_events=$((store_events + event_count))
        log "  ✓ $cam_id — $event_count events"
    done
 
    total_events=$((total_events + store_events))
    stores_processed=$((stores_processed + 1))
    log "  Store $store_id complete: $store_events events"
done
 
# Merge all JSONL files into a single output for bulk ingest
merged="$OUTPUT_DIR/all_events.jsonl"
cat "$OUTPUT_DIR"/*.jsonl > "$merged" 2>/dev/null || true
total_lines=$(wc -l < "$merged" 2>/dev/null || echo 0)
 
log ""
log "═══════════════════════════════════════"
log " Stores processed : $stores_processed"
log " Total events     : $total_events"
log " Merged output    : $merged ($total_lines lines)"
 
# Bulk ingest into API if requested
if [[ -n "$API_URL" ]]; then
    log ""
    log "Bulk-ingesting $merged → $API_URL/events/ingest"
    python3 - <<EOF
import json, httpx, sys
from pathlib import Path
 
path = Path("$merged")
api  = "$API_URL"
batch_size = 500
batch = []
sent = 0
errors = 0
 
with httpx.Client(timeout=30) as client:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                batch.append(json.loads(line))
            except json.JSONDecodeError:
                errors += 1
                continue
 
            if len(batch) >= batch_size:
                r = client.post(f"{api}/events/ingest", json={"events": batch})
                if r.status_code not in (200, 201, 207):
                    print(f"WARN: ingest returned {r.status_code}")
                    errors += 1
                sent += len(batch)
                batch = []
 
    if batch:
        r = client.post(f"{api}/events/ingest", json={"events": batch})
        sent += len(batch)
 
print(f"Ingested {sent} events | errors={errors}")
EOF
fi
 
log "Done."