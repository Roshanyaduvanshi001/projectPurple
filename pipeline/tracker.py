"""
tracker.py — Tracking, Re-Identification, and Staff Classification.
 
Components
──────────
ByteTracker        Simplified ByteTrack-style multi-object tracker using IoU
                   association + Kalman filter position prediction.
 
ReIDBank           Appearance embedding store for cross-camera / re-entry
                   deduplication. Uses colour histogram as lightweight Re-ID
                   (drop-in replaceable with OSNet/torchreid).
 
StaffClassifier    Classifies a bounding box as staff by detecting the dominant
                   uniform colour (configurable HSV range) on the torso ROI.
"""
 
from __future__ import annotations
 
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
 
import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment  # type: ignore
 
log = logging.getLogger("tracker")
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Kalman Filter — simple constant-velocity model for bounding box centre
# ──────────────────────────────────────────────────────────────────────────────
 
class KalmanBoxTracker:
    """
    4-state Kalman: [cx, cy, vx, vy]
    Observation: [cx, cy]
    """
 
    _count = 0
 
    def __init__(self, bbox: np.ndarray) -> None:
        KalmanBoxTracker._count += 1
        self.id          = KalmanBoxTracker._count
        self.hits        = 1
        self.no_match    = 0
        self.age         = 0
        self.last_bbox   = bbox.copy()
 
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        w,  h  = bbox[2] - bbox[0], bbox[3] - bbox[1]
 
        # State
        self.x = np.array([[cx], [cy], [0.0], [0.0]])
        # Covariance
        self.P = np.diag([10.0, 10.0, 100.0, 100.0])
        # Transition
        self.F = np.array([[1,0,1,0],[0,1,0,1],[0,0,1,0],[0,0,0,1]], dtype=float)
        # Observation
        self.H = np.array([[1,0,0,0],[0,1,0,0]], dtype=float)
        # Process noise
        self.Q = np.diag([1.0, 1.0, 0.1, 0.1])
        # Measurement noise
        self.R = np.diag([5.0, 5.0])
        # Store width/height separately (Kalman only tracks centre)
        self._w = w
        self._h = h
 
    def predict(self) -> np.ndarray:
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        self.age += 1
        return self._to_bbox()
 
    def update(self, bbox: np.ndarray) -> None:
        self.last_bbox = bbox.copy()
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        self._w = bbox[2] - bbox[0]
        self._h = bbox[3] - bbox[1]
 
        z = np.array([[cx], [cy]])
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ (z - self.H @ self.x)
        self.P = (np.eye(4) - K @ self.H) @ self.P
        self.hits      += 1
        self.no_match   = 0
 
    def _to_bbox(self) -> np.ndarray:
        cx, cy = float(self.x[0]), float(self.x[1])
        return np.array([
            cx - self._w / 2, cy - self._h / 2,
            cx + self._w / 2, cy + self._h / 2,
        ])
 
 
def _iou(a: np.ndarray, b: np.ndarray) -> float:
    """Intersection-over-Union of two [x1,y1,x2,y2] boxes."""
    ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = (a[2]-a[0]) * (a[3]-a[1])
    area_b = (b[2]-b[0]) * (b[3]-b[1])
    union = area_a + area_b - inter + 1e-9
    return inter / union
 
 
def _iou_matrix(trackers: list[np.ndarray], detections: list[np.ndarray]) -> np.ndarray:
    m = np.zeros((len(trackers), len(detections)), dtype=np.float32)
    for i, t in enumerate(trackers):
        for j, d in enumerate(detections):
            m[i, j] = _iou(t, d)
    return m
 
 
# ──────────────────────────────────────────────────────────────────────────────
# ByteTracker
# ──────────────────────────────────────────────────────────────────────────────
 
class ByteTracker:
    """
    Simplified ByteTrack:
    - High-confidence detections matched first (IoU).
    - Low-confidence detections matched to unmatched tracks (IoU).
    - Tracks kept alive for MAX_AGE frames before deletion.
    - MIN_HITS frames before a track is confirmed.
    """
 
    MAX_AGE   = 30   # frames before lost track is deleted
    MIN_HITS  = 3    # frames before track is confirmed
    IOU_HIGH  = 0.5  # IoU threshold for high-conf matching
    IOU_LOW   = 0.3  # IoU threshold for low-conf fallback
    CONF_HIGH = 0.5  # detection confidence split
 
    def __init__(self) -> None:
        self._trackers: list[KalmanBoxTracker] = []
        KalmanBoxTracker._count = 0  # reset for test isolation
 
    def update(
        self,
        detections: list[np.ndarray],  # each: [x1,y1,x2,y2,conf]
        frame: np.ndarray,             # not used here; kept for API parity
    ) -> list[tuple[int, np.ndarray, float]]:
        """
        Returns list of (track_id, bbox[x1,y1,x2,y2], conf) for confirmed tracks.
        """
        if not detections:
            # Advance all trackers
            for t in self._trackers:
                t.predict()
                t.no_match += 1
            self._trackers = [t for t in self._trackers if t.no_match <= self.MAX_AGE]
            return []
 
        dets_arr = np.array(detections)               # (N, 5)
        high_mask = dets_arr[:, 4] >= self.CONF_HIGH
        high_dets = dets_arr[high_mask]
        low_dets  = dets_arr[~high_mask]
 
        # Predict all existing tracks
        predicted = [t.predict() for t in self._trackers]
 
        matched_t: set[int] = set()
        matched_d: set[int] = set()
 
        # ── Pass 1: high-conf ────────────────────────────────────────────────
        if len(predicted) and len(high_dets):
            iou_mat = _iou_matrix(predicted, high_dets[:, :4].tolist())
            cost    = 1 - iou_mat
            ti, di  = linear_sum_assignment(cost)
            for t_idx, d_idx in zip(ti, di):
                if iou_mat[t_idx, d_idx] >= self.IOU_HIGH:
                    self._trackers[t_idx].update(high_dets[d_idx, :4])
                    self._trackers[t_idx].last_conf = float(high_dets[d_idx, 4])
                    matched_t.add(t_idx)
                    matched_d.add(d_idx)
 
        # ── Pass 2: low-conf against unmatched tracks ────────────────────────
        unmatched_t = [i for i in range(len(self._trackers)) if i not in matched_t]
        if unmatched_t and len(low_dets):
            pred_unmatched = [predicted[i] for i in unmatched_t]
            iou_mat2 = _iou_matrix(pred_unmatched, low_dets[:, :4].tolist())
            cost2    = 1 - iou_mat2
            ti2, di2 = linear_sum_assignment(cost2)
            for ti_local, d_idx in zip(ti2, di2):
                t_idx = unmatched_t[ti_local]
                if iou_mat2[ti_local, d_idx] >= self.IOU_LOW:
                    self._trackers[t_idx].update(low_dets[d_idx, :4])
                    self._trackers[t_idx].last_conf = float(low_dets[d_idx, 4])
                    matched_t.add(t_idx)
 
        # ── Unmatched detections → new trackers ──────────────────────────────
        all_high_indices  = set(range(len(high_dets)))
        new_det_indices   = all_high_indices - matched_d
        for d_idx in new_det_indices:
            t = KalmanBoxTracker(high_dets[d_idx, :4])
            t.last_conf = float(high_dets[d_idx, 4])
            self._trackers.append(t)
 
        # ── Age out unmatched tracks ─────────────────────────────────────────
        for i, t in enumerate(self._trackers):
            if i not in matched_t:
                t.no_match += 1
 
        self._trackers = [t for t in self._trackers if t.no_match <= self.MAX_AGE]
 
        # ── Return confirmed tracks ───────────────────────────────────────────
        results = []
        for t in self._trackers:
            if t.hits >= self.MIN_HITS and t.no_match == 0:
                bbox = t.last_bbox
                conf = getattr(t, "last_conf", 0.5)
                results.append((t.id, bbox, conf))
        return results
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Re-ID Bank
# ──────────────────────────────────────────────────────────────────────────────
 
@dataclass
class _ReIDEntry:
    visitor_id: str
    embedding: np.ndarray
    last_seen: float
    exited: bool = False
    exit_time: Optional[float] = None
 
 
class ReIDBank:
    """
    Lightweight Re-ID using colour histogram on the torso region.
 
    For production: replace `extract()` with an OSNet forward pass.
    Cosine similarity threshold tuned for 1080p retail footage.
    """
 
    SIMILARITY_THRESHOLD = 0.85
    REENTRY_GAP_MIN      = 10.0   # seconds — ignore if < 10s (dedup with tracking)
 
    def __init__(self, window_seconds: float = 300) -> None:
        self.window_seconds = window_seconds
        self._track_map: dict[int, str]          = {}   # track_id → visitor_id
        self._entries:   dict[str, _ReIDEntry]   = {}   # visitor_id → entry
 
    def extract(self, frame: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        """
        Extract colour histogram from torso region (middle third of bbox).
        Returns L2-normalised 96-dim vector (3 channels × 32 bins).
        """
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        h = y2 - y1
        # Torso = middle vertical third
        ty1 = y1 + h // 3
        ty2 = y1 + 2 * h // 3
        roi  = frame[ty1:ty2, x1:x2]
        if roi.size == 0:
            return np.zeros(96)
 
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist(
            [hsv], [0, 1, 2], None, [16, 4, 4], [0,180, 0,256, 0,256]
        ).flatten().astype(np.float32)
 
        # Reduce to 96 dims via simple binning
        # (16*4*4 = 256 → grouped to 96 for speed)
        hist = cv2.resize(hist.reshape(1, -1), (96, 1)).flatten()
        norm = np.linalg.norm(hist)
        return hist / (norm + 1e-9)
 
    def _cosine_sim(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))  # both L2-normalised
 
    def match_or_register(
        self, track_id: int, embedding: np.ndarray
    ) -> tuple[str, bool]:
        """
        Returns (visitor_id, is_reentry).
        """
        now = time.time()
 
        # Same track seen before
        if track_id in self._track_map:
            vid = self._track_map[track_id]
            if vid in self._entries:
                self._entries[vid].last_seen = now
                self._entries[vid].embedding = embedding
            return vid, False
 
        # Prune stale entries
        self._entries = {
            vid: e for vid, e in self._entries.items()
            if (now - e.last_seen) < self.window_seconds
        }
 
        # Search for re-entry match among recently-exited visitors
        best_sim   = -1.0
        best_vid   = None
        for vid, entry in self._entries.items():
            if not entry.exited:
                continue
            if entry.exit_time and (now - entry.exit_time) < self.REENTRY_GAP_MIN:
                continue
            sim = self._cosine_sim(embedding, entry.embedding)
            if sim > best_sim:
                best_sim = sim
                best_vid = vid
 
        is_reentry = False
        if best_vid and best_sim >= self.SIMILARITY_THRESHOLD:
            visitor_id    = best_vid
            is_reentry    = True
            entry         = self._entries[visitor_id]
            entry.exited  = False
            entry.last_seen = now
            entry.embedding = embedding
            log.debug("Re-entry detected: %s (sim=%.3f)", visitor_id, best_sim)
        else:
            visitor_id = "VIS_" + uuid.uuid4().hex[:6]
            self._entries[visitor_id] = _ReIDEntry(
                visitor_id=visitor_id,
                embedding=embedding,
                last_seen=now,
            )
 
        self._track_map[track_id] = visitor_id
        return visitor_id, is_reentry
 
    def mark_exited(self, visitor_id: str, ts: float) -> None:
        if visitor_id in self._entries:
            self._entries[visitor_id].exited    = True
            self._entries[visitor_id].exit_time = ts
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Staff Classifier
# ──────────────────────────────────────────────────────────────────────────────
 
# Default HSV range for typical retail staff uniform (e.g. dark blue/black shirt)
# Adjust per store layout spec.  Loaded from store_layout.json if provided.
_DEFAULT_UNIFORM_HSV = [
    # (lower_H, lower_S, lower_V, upper_H, upper_S, upper_V)
    (100, 80, 20, 130, 255, 200),   # dark blue
    (0,   0,   0,  180,  30,  50),  # black / very dark
]
 
 
class StaffClassifier:
    """
    Classifies a bounding box as staff by measuring the fraction of torso pixels
    that fall within the configured uniform HSV range(s).
 
    Threshold: if ≥ 40% of torso pixels match any uniform band → staff.
 
    For higher accuracy: replace with a fine-tuned binary classifier or
    prompt a VLM (GPT-4V / Claude Vision) on a keyframe sample.
    """
 
    STAFF_PIXEL_RATIO = 0.40
 
    def __init__(self, hsv_ranges: Optional[list[tuple]] = None) -> None:
        self.hsv_ranges = hsv_ranges or _DEFAULT_UNIFORM_HSV
 
    def classify(self, frame: np.ndarray, bbox: np.ndarray) -> bool:
        """Return True if the torso region looks like a staff uniform."""
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        h = y2 - y1
        ty1 = y1 + h // 3
        ty2 = y1 + 2 * h // 3
        roi = frame[ty1:ty2, x1:x2]
        if roi.size == 0:
            return False
 
        hsv  = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lo_h, lo_s, lo_v, hi_h, hi_s, hi_v in self.hsv_ranges:
            lower = np.array([lo_h, lo_s, lo_v])
            upper = np.array([hi_h, hi_s, hi_v])
            mask  = cv2.bitwise_or(mask, cv2.inRange(hsv, lower, upper))
 
        ratio = mask.sum() / (mask.size + 1e-9)
        return bool(ratio >= self.STAFF_PIXEL_RATIO)
 