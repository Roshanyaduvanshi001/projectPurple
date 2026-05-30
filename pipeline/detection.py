
"""
detect.py — Main detection + tracking orchestrator.
 
Pipeline:
  1. Load video clip
  2. Run YOLOv8 person detection (class=0) per frame
  3. Feed detections to ByteTrack for temporal ID assignment
  4. Apply Re-ID via appearance embeddings for cross-camera dedup
  5. Classify staff via colour histogram on torso ROI
  6. Determine entry/exit by crossing the threshold line
  7. Emit structured events via emit.py
 
Usage:
    python detect.py --video clips/STORE_BLR_002/entry.mp4 \
                     --store STORE_BLR_002 \
                     --camera CAM_ENTRY_01 \
                     --layout store_layout.json \
                     --output events.jsonl
"""
 
from __future__ import annotations
 
import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
 
import cv2
import numpy as np
 
from emit import EventEmitter
from tracker import ByteTracker, ReIDBank, StaffClassifier
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("detect")
 
# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
YOLO_CONF_THRESHOLD = 0.35       # min detection confidence passed to tracker
YOLO_IOU_THRESHOLD  = 0.45
PERSON_CLASS_ID     = 0          # COCO class 0 = person
ENTRY_LINE_RATIO    = 0.35       # fraction of frame height for entry/exit line
ZONE_DWELL_INTERVAL = 30         # seconds between ZONE_DWELL emissions
REID_WINDOW_SECONDS = 300        # 5-min window for re-entry detection
STAFF_AREA_FRAMES   = 30         # frames needed before labelling a track as staff
 
 
@dataclass
class TrackState:
    """Per-track runtime state."""
    track_id: int
    visitor_id: str
    is_staff: bool = False
    staff_votes: int = 0
    entry_emitted: bool = False
    exit_emitted: bool = False
    current_zone: Optional[str] = None
    zone_entry_time: Optional[float] = None
    last_dwell_emit: Optional[float] = None
    billing_entered_time: Optional[float] = None
    session_seq: int = 0
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
 
def _load_zones(layout_path: Path, store_id: str, camera_id: str) -> list[dict]:
    """Return zone polygons for a given store + camera from store_layout.json."""
    with open(layout_path) as f:
        layout = json.load(f)
    store = next((s for s in layout["stores"] if s["store_id"] == store_id), None)
    if store is None:
        log.warning("store %s not found in layout — using empty zones", store_id)
        return []
    zones = []
    for z in store.get("zones", []):
        cameras = z.get("cameras", [])
        if camera_id in cameras or not cameras:
            zones.append(z)
    return zones
 
 
def _point_in_polygon(pt: tuple[float, float], poly: list[list[float]]) -> bool:
    """Ray-casting polygon containment test."""
    x, y = pt
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside
 
 
def _get_zone(cx: float, cy: float, zones: list[dict]) -> Optional[str]:
    """Return zone_id if point falls inside any zone polygon."""
    for z in zones:
        poly = z.get("polygon", [])
        if poly and _point_in_polygon((cx, cy), poly):
            return z["zone_id"]
    return None
 
 
def _bbox_centre(bbox: np.ndarray) -> tuple[float, float]:
    """Return (cx, cy) from [x1,y1,x2,y2]."""
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
 
 
def _crosses_line(
    prev_cy: float,
    curr_cy: float,
    line_y: float,
) -> Optional[str]:
    """Return 'ENTRY', 'EXIT', or None based on crossing direction."""
    if prev_cy > line_y >= curr_cy:
        return "ENTRY"   # moving upward = toward camera = into store
    if prev_cy < line_y <= curr_cy:
        return "EXIT"    # moving downward = away from camera = leaving
    return None
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Main processor
# ──────────────────────────────────────────────────────────────────────────────
 
class ClipProcessor:
    def __init__(
        self,
        video_path: Path,
        store_id: str,
        camera_id: str,
        layout_path: Path,
        clip_start_ts: str,
        emitter: EventEmitter,
    ):
        self.video_path    = video_path
        self.store_id      = store_id
        self.camera_id     = camera_id
        self.clip_start_ts = clip_start_ts
        self.emitter       = emitter
        self.zones         = _load_zones(layout_path, store_id, camera_id)
 
        # Lazy import heavy deps so they can be mocked in tests
        try:
            from ultralytics import YOLO  # type: ignore
            self.model = YOLO("yolov8n.pt")  # nano — fast, good enough for 1080p 15fps
            log.info("YOLOv8 nano loaded")
        except ImportError:
            log.error("ultralytics not installed — pip install ultralytics")
            raise
 
        self.tracker        = ByteTracker()
        self.reid_bank      = ReIDBank(window_seconds=REID_WINDOW_SECONDS)
        self.staff_clf      = StaffClassifier()
        self.track_states: dict[int, TrackState] = {}
        self.prev_centres:  dict[int, float]      = {}  # track_id -> prev cy
 
    # ── frame-level ──────────────────────────────────────────────────────────
 
    def _frame_ts(self, cap: cv2.VideoCapture) -> float:
        """Current frame wall-clock time based on clip start + frame position."""
        from datetime import datetime, timezone
        pos_ms  = cap.get(cv2.CAP_PROP_POS_MSEC)
        base_ts = datetime.fromisoformat(
            self.clip_start_ts.replace("Z", "+00:00")
        ).timestamp()
        return base_ts + pos_ms / 1000.0
 
    def _detect(self, frame: np.ndarray) -> list[np.ndarray]:
        """Run YOLOv8 and return list of [x1,y1,x2,y2,conf] arrays for persons."""
        results = self.model(
            frame,
            classes=[PERSON_CLASS_ID],
            conf=YOLO_CONF_THRESHOLD,
            iou=YOLO_IOU_THRESHOLD,
            verbose=False,
        )
        dets = []
        for r in results:
            for box in r.boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                dets.append(np.append(xyxy, conf))
        return dets
 
    # ── per-track logic ───────────────────────────────────────────────────────
 
    def _get_or_create_state(
        self, track_id: int, frame: np.ndarray, bbox: np.ndarray, conf: float
    ) -> TrackState:
        if track_id not in self.track_states:
            # Query Re-ID bank — may return existing visitor_id for re-entry
            app_vec = self.reid_bank.extract(frame, bbox)
            visitor_id, is_reentry = self.reid_bank.match_or_register(
                track_id, app_vec
            )
            state = TrackState(track_id=track_id, visitor_id=visitor_id)
            self.track_states[track_id] = state
            if is_reentry:
                self.emitter.emit_reentry(
                    store_id=self.store_id,
                    camera_id=self.camera_id,
                    visitor_id=visitor_id,
                    confidence=conf,
                    session_seq=0,
                )
        return self.track_states[track_id]
 
    def _update_staff_vote(
        self, state: TrackState, frame: np.ndarray, bbox: np.ndarray
    ) -> None:
        """Accumulate staff classification votes."""
        vote = self.staff_clf.classify(frame, bbox)
        if vote:
            state.staff_votes += 1
        # Commit after enough evidence
        if not state.is_staff and state.staff_votes >= 3:
            state.is_staff = True
            log.debug("track %d promoted to staff", state.track_id)
 
    def _handle_entry_exit(
        self,
        state: TrackState,
        cy: float,
        line_y: float,
        frame_ts: float,
        conf: float,
    ) -> None:
        """Emit ENTRY / EXIT based on threshold line crossing."""
        prev_cy = self.prev_centres.get(state.track_id)
        if prev_cy is None:
            self.prev_centres[state.track_id] = cy
            return
 
        direction = _crosses_line(prev_cy, cy, line_y)
        self.prev_centres[state.track_id] = cy
 
        if direction == "ENTRY" and not state.entry_emitted:
            state.entry_emitted = True
            state.exit_emitted  = False
            state.session_seq   = 0
            self.emitter.emit_entry(
                store_id=self.store_id,
                camera_id=self.camera_id,
                visitor_id=state.visitor_id,
                is_staff=state.is_staff,
                confidence=conf,
                frame_ts=frame_ts,
                session_seq=state.session_seq,
            )
            state.session_seq += 1
 
        elif direction == "EXIT" and state.entry_emitted and not state.exit_emitted:
            state.exit_emitted  = True
            state.entry_emitted = False
            self.emitter.emit_exit(
                store_id=self.store_id,
                camera_id=self.camera_id,
                visitor_id=state.visitor_id,
                is_staff=state.is_staff,
                confidence=conf,
                frame_ts=frame_ts,
                session_seq=state.session_seq,
            )
            self.reid_bank.mark_exited(state.visitor_id, frame_ts)
 
    def _handle_zones(
        self,
        state: TrackState,
        cx: float,
        cy: float,
        frame_ts: float,
        conf: float,
        queue_depth: int,
    ) -> None:
        """Emit ZONE_ENTER / ZONE_EXIT / ZONE_DWELL / BILLING_* events."""
        zone_id = _get_zone(cx, cy, self.zones)
 
        # Zone change
        if zone_id != state.current_zone:
            if state.current_zone is not None:
                self.emitter.emit_zone_exit(
                    store_id=self.store_id,
                    camera_id=self.camera_id,
                    visitor_id=state.visitor_id,
                    zone_id=state.current_zone,
                    is_staff=state.is_staff,
                    confidence=conf,
                    frame_ts=frame_ts,
                    session_seq=state.session_seq,
                    dwell_ms=int((frame_ts - (state.zone_entry_time or frame_ts)) * 1000),
                )
                state.session_seq += 1
 
                # Billing abandonment: left billing without a purchase
                if state.current_zone == "BILLING" and state.billing_entered_time:
                    self.emitter.emit_billing_abandon(
                        store_id=self.store_id,
                        camera_id=self.camera_id,
                        visitor_id=state.visitor_id,
                        is_staff=state.is_staff,
                        confidence=conf,
                        frame_ts=frame_ts,
                        session_seq=state.session_seq,
                    )
                    state.billing_entered_time = None
                    state.session_seq += 1
 
            if zone_id is not None:
                is_billing = zone_id == "BILLING"
                if is_billing and queue_depth > 0:
                    self.emitter.emit_billing_queue_join(
                        store_id=self.store_id,
                        camera_id=self.camera_id,
                        visitor_id=state.visitor_id,
                        is_staff=state.is_staff,
                        confidence=conf,
                        frame_ts=frame_ts,
                        session_seq=state.session_seq,
                        queue_depth=queue_depth,
                    )
                    state.billing_entered_time = frame_ts
                    state.session_seq += 1
                else:
                    self.emitter.emit_zone_enter(
                        store_id=self.store_id,
                        camera_id=self.camera_id,
                        visitor_id=state.visitor_id,
                        zone_id=zone_id,
                        is_staff=state.is_staff,
                        confidence=conf,
                        frame_ts=frame_ts,
                        session_seq=state.session_seq,
                    )
                    state.session_seq += 1
 
            state.current_zone   = zone_id
            state.zone_entry_time = frame_ts if zone_id else None
            state.last_dwell_emit = frame_ts if zone_id else None
 
        # Dwell: emit every ZONE_DWELL_INTERVAL seconds
        elif (
            zone_id is not None
            and state.last_dwell_emit is not None
            and (frame_ts - state.last_dwell_emit) >= ZONE_DWELL_INTERVAL
        ):
            elapsed_ms = int((frame_ts - state.last_dwell_emit) * 1000)
            self.emitter.emit_zone_dwell(
                store_id=self.store_id,
                camera_id=self.camera_id,
                visitor_id=state.visitor_id,
                zone_id=zone_id,
                is_staff=state.is_staff,
                confidence=conf,
                frame_ts=frame_ts,
                session_seq=state.session_seq,
                dwell_ms=elapsed_ms,
            )
            state.last_dwell_emit = frame_ts
            state.session_seq += 1
 
    # ── main loop ─────────────────────────────────────────────────────────────
 
    def process(self) -> int:
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")
 
        fps    = cap.get(cv2.CAP_PROP_FPS) or 15.0
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        line_y = height * ENTRY_LINE_RATIO
 
        log.info(
            "Processing %s @ %.1f fps %dx%d — entry line y=%.0f",
            self.video_path.name, fps, width, height, line_y,
        )
 
        frame_num   = 0
        event_count = 0
        t0          = time.perf_counter()
 
        while True:
            ret, frame = cap.read()
            if not ret:
                break
 
            frame_num += 1
            frame_ts   = self._frame_ts(cap)
 
            # ── detect ──────────────────────────────────────────────────────
            detections = self._detect(frame)
 
            # ── track ───────────────────────────────────────────────────────
            tracks = self.tracker.update(detections, frame)
            # tracks: list of (track_id, bbox[x1,y1,x2,y2], conf)
 
            # Estimate billing queue depth (tracks in BILLING zone)
            billing_tracks = sum(
                1 for (_, bbox, _) in tracks
                if _get_zone(*_bbox_centre(bbox), self.zones) == "BILLING"
            )
            queue_depth = max(0, billing_tracks - 1)
 
            for track_id, bbox, conf in tracks:
                cx, cy = _bbox_centre(bbox)
                state  = self._get_or_create_state(track_id, frame, bbox, conf)
 
                self._update_staff_vote(state, frame, bbox)
 
                # Only entry camera processes threshold line
                if "ENTRY" in self.camera_id:
                    self._handle_entry_exit(state, cy, line_y, frame_ts, conf)
 
                if state.entry_emitted:
                    self._handle_zones(
                        state, cx, cy, frame_ts, conf, queue_depth
                    )
 
            if frame_num % 300 == 0:
                elapsed = time.perf_counter() - t0
                log.info(
                    "Frame %d | tracks=%d | events=%d | %.1f fps",
                    frame_num, len(tracks), self.emitter.count, frame_num / elapsed,
                )
 
        cap.release()
        elapsed = time.perf_counter() - t0
        log.info(
            "Done: %d frames in %.1fs — %d events emitted",
            frame_num, elapsed, self.emitter.count,
        )
        return self.emitter.count
 
 
# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
 
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CCTV detection pipeline")
    p.add_argument("--video",    required=True, help="Path to video clip")
    p.add_argument("--store",    required=True, help="Store ID e.g. STORE_BLR_002")
    p.add_argument("--camera",   required=True, help="Camera ID e.g. CAM_ENTRY_01")
    p.add_argument("--layout",   default="store_layout.json")
    p.add_argument("--output",   default="events.jsonl")
    p.add_argument("--clip-start", default="2026-03-03T09:00:00Z",
                   help="ISO-8601 UTC timestamp of first frame")
    p.add_argument("--api-url",  default=None,
                   help="If set, stream events to API instead of file")
    return p.parse_args()
 
 
def main() -> None:
    args = parse_args()
 
    emitter = EventEmitter(
        output_path=Path(args.output),
        api_url=args.api_url,
        batch_size=50,
    )
 
    processor = ClipProcessor(
        video_path=Path(args.video),
        store_id=args.store,
        camera_id=args.camera,
        layout_path=Path(args.layout),
        clip_start_ts=args.clip_start,
        emitter=emitter,
    )
 
    try:
        count = processor.process()
        emitter.flush()
        log.info("Pipeline complete — %d events written to %s", count, args.output)
    except KeyboardInterrupt:
        log.info("Interrupted — flushing partial output")
        emitter.flush()
        sys.exit(0)
 
 
if __name__ == "__main__":
    main()
