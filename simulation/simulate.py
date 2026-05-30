"""
simulate.py — Event simulation engine for Store Intelligence.

Supports:
- Chronological replay of existing JSONL streams at adjustable speed (--speed).
- Continuous, realistic synthetic event generation to showcase real-time WebSocket push.
"""

import sys
import time
import json
import uuid
import random
import argparse
from datetime import datetime, timezone
from pathlib import Path
import httpx

# Color helper functions for clean terminal feedback
def print_info(msg: str):
    print(f"\033[94m[INFO]\033[0m {msg}")

def print_success(msg: str):
    print(f"\033[92m[SUCCESS]\033[0m {msg}")

def print_warning(msg: str):
    print(f"\033[93m[WARN]\033[0m {msg}")

def print_error(msg: str):
    print(f"\033[91m[ERROR]\033[0m {msg}", file=sys.stderr)


class EventGenerator:
    """Generates continuous, highly-realistic store event sequences."""
    
    def __init__(self, store_id: str):
        self.store_id = store_id
        self.active_customers = {} # visitor_id -> {state, start_ts, current_zone, path}
        self.camera_map = {
            "ENTRY": "CAM_ENTRY_01",
            "EXIT": "CAM_ENTRY_01",
            "ZONE_ENTER": "CAM_FLOOR_01",
            "ZONE_EXIT": "CAM_FLOOR_01",
            "ZONE_DWELL": "CAM_FLOOR_01",
            "BILLING_QUEUE_JOIN": "CAM_BILLING_01",
            "BILLING_QUEUE_ABANDON": "CAM_BILLING_01"
        }
        self.zones = ["SKINCARE", "HAIRCARE", "PHARMACY", "BILLING"]
        
    def next_event(self) -> dict:
        now_dt = datetime.now(timezone.utc)
        now_ts = now_dt.timestamp()
        now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Decide whether to spawn a new customer or advance an existing one
        spawn_new = random.random() < 0.25 or not self.active_customers
        
        if spawn_new and len(self.active_customers) < 15:
            # Create new visitor
            visitor_id = f"visitor_{random.randint(1000, 9999)}"
            is_staff = random.random() < 0.08  # 8% staff
            self.active_customers[visitor_id] = {
                "visitor_id": visitor_id,
                "is_staff": is_staff,
                "state": "ENTRY",
                "start_ts": now_ts,
                "current_zone": None,
                "dwells_remaining": random.randint(1, 3),
                "reentries": 0
            }
            
            return {
                "event_id": str(uuid.uuid4()),
                "store_id": self.store_id,
                "camera_id": self.camera_map["ENTRY"],
                "visitor_id": visitor_id,
                "event_type": "ENTRY",
                "timestamp": now_iso,
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": is_staff,
                "confidence": round(random.uniform(0.85, 0.99), 2),
                "metadata": {"session_seq": 0}
            }
            
        else:
            # Advance an existing customer
            visitor_id = random.choice(list(self.active_customers.keys()))
            cust = self.active_customers[visitor_id]
            is_staff = cust["is_staff"]
            
            if cust["state"] == "ENTRY":
                # Move to a shopping zone
                zone = random.choice(self.zones[:-1])  # Exclude BILLING initially
                cust["state"] = "ZONE_ENTER"
                cust["current_zone"] = zone
                cust["zone_start_ts"] = now_ts
                
                return {
                    "event_id": str(uuid.uuid4()),
                    "store_id": self.store_id,
                    "camera_id": self.camera_map["ZONE_ENTER"],
                    "visitor_id": visitor_id,
                    "event_type": "ZONE_ENTER",
                    "timestamp": now_iso,
                    "zone_id": zone,
                    "dwell_ms": 0,
                    "is_staff": is_staff,
                    "confidence": round(random.uniform(0.80, 0.98), 2),
                    "metadata": {"session_seq": 0}
                }
                
            elif cust["state"] == "ZONE_ENTER":
                # Either trigger a ZONE_DWELL or ZONE_EXIT
                zone = cust["current_zone"]
                action = random.choice(["DWELL", "EXIT"])
                
                if action == "DWELL":
                    cust["state"] = "ZONE_DWELL"
                    dwell_time = random.randint(15000, 45000)
                    return {
                        "event_id": str(uuid.uuid4()),
                        "store_id": self.store_id,
                        "camera_id": self.camera_map["ZONE_DWELL"],
                        "visitor_id": visitor_id,
                        "event_type": "ZONE_DWELL",
                        "timestamp": now_iso,
                        "zone_id": zone,
                        "dwell_ms": dwell_time,
                        "is_staff": is_staff,
                        "confidence": round(random.uniform(0.85, 0.99), 2),
                        "metadata": {"session_seq": 0}
                    }
                else:
                    cust["state"] = "ZONE_EXIT"
                    dwell_time = int((now_ts - cust["zone_start_ts"]) * 1000)
                    cust["current_zone"] = None
                    return {
                        "event_id": str(uuid.uuid4()),
                        "store_id": self.store_id,
                        "camera_id": self.camera_map["ZONE_EXIT"],
                        "visitor_id": visitor_id,
                        "event_type": "ZONE_EXIT",
                        "timestamp": now_iso,
                        "zone_id": zone,
                        "dwell_ms": dwell_time,
                        "is_staff": is_staff,
                        "confidence": round(random.uniform(0.85, 0.99), 2),
                        "metadata": {"session_seq": 0}
                    }
                    
            elif cust["state"] in ("ZONE_DWELL", "ZONE_EXIT"):
                # Decide next destination
                if cust["state"] == "ZONE_DWELL":
                    # Exit the zone first
                    cust["state"] = "ZONE_EXIT"
                    zone = cust["current_zone"]
                    dwell_time = int((now_ts - cust["zone_start_ts"]) * 1000)
                    cust["current_zone"] = None
                    return {
                        "event_id": str(uuid.uuid4()),
                        "store_id": self.store_id,
                        "camera_id": self.camera_map["ZONE_EXIT"],
                        "visitor_id": visitor_id,
                        "event_type": "ZONE_EXIT",
                        "timestamp": now_iso,
                        "zone_id": zone,
                        "dwell_ms": dwell_time,
                        "is_staff": is_staff,
                        "confidence": round(random.uniform(0.85, 0.99), 2),
                        "metadata": {"session_seq": 0}
                    }
                
                cust["dwells_remaining"] -= 1
                if cust["dwells_remaining"] > 0:
                    # Enter another zone
                    zone = random.choice(self.zones[:-1])
                    cust["state"] = "ZONE_ENTER"
                    cust["current_zone"] = zone
                    cust["zone_start_ts"] = now_ts
                    return {
                        "event_id": str(uuid.uuid4()),
                        "store_id": self.store_id,
                        "camera_id": self.camera_map["ZONE_ENTER"],
                        "visitor_id": visitor_id,
                        "event_type": "ZONE_ENTER",
                        "timestamp": now_iso,
                        "zone_id": zone,
                        "dwell_ms": 0,
                        "is_staff": is_staff,
                        "confidence": round(random.uniform(0.80, 0.98), 2),
                        "metadata": {"session_seq": 0}
                    }
                else:
                    # Proceed to checkout if not staff
                    if is_staff:
                        cust["state"] = "EXIT"
                        return {
                            "event_id": str(uuid.uuid4()),
                            "store_id": self.store_id,
                            "camera_id": self.camera_map["EXIT"],
                            "visitor_id": visitor_id,
                            "event_type": "EXIT",
                            "timestamp": now_iso,
                            "zone_id": None,
                            "dwell_ms": int((now_ts - cust["start_ts"]) * 1000),
                            "is_staff": is_staff,
                            "confidence": round(random.uniform(0.90, 0.99), 2),
                            "metadata": {"session_seq": 0}
                        }
                    else:
                        cust["state"] = "BILLING"
                        cust["billing_start_ts"] = now_ts
                        return {
                            "event_id": str(uuid.uuid4()),
                            "store_id": self.store_id,
                            "camera_id": self.camera_map["BILLING_QUEUE_JOIN"],
                            "visitor_id": visitor_id,
                            "event_type": "BILLING_QUEUE_JOIN",
                            "timestamp": now_iso,
                            "zone_id": "BILLING",
                            "dwell_ms": 0,
                            "is_staff": is_staff,
                            "confidence": round(random.uniform(0.85, 0.98), 2),
                            "metadata": {
                                "queue_depth": len([c for c in self.active_customers.values() if c["state"] == "BILLING"]),
                                "session_seq": 0
                            }
                        }
                        
            elif cust["state"] == "BILLING":
                # Purchase (Exit store) or Abandon
                abandon = random.random() < 0.12  # 12% abandonment
                if abandon:
                    cust["state"] = "EXIT"
                    return {
                        "event_id": str(uuid.uuid4()),
                        "store_id": self.store_id,
                        "camera_id": self.camera_map["BILLING_QUEUE_ABANDON"],
                        "visitor_id": visitor_id,
                        "event_type": "BILLING_QUEUE_ABANDON",
                        "timestamp": now_iso,
                        "zone_id": "BILLING",
                        "dwell_ms": int((now_ts - cust["billing_start_ts"]) * 1000),
                        "is_staff": is_staff,
                        "confidence": round(random.uniform(0.85, 0.99), 2),
                        "metadata": {"session_seq": 0}
                    }
                else:
                    # Successfully purchased -> Exit
                    cust["state"] = "EXIT"
                    return {
                        "event_id": str(uuid.uuid4()),
                        "store_id": self.store_id,
                        "camera_id": self.camera_map["EXIT"],
                        "visitor_id": visitor_id,
                        "event_type": "EXIT",
                        "timestamp": now_iso,
                        "zone_id": None,
                        "dwell_ms": int((now_ts - cust["start_ts"]) * 1000),
                        "is_staff": is_staff,
                        "confidence": round(random.uniform(0.85, 0.99), 2),
                        "metadata": {"session_seq": 0}
                    }
                    
            elif cust["state"] == "EXIT":
                # Remove from active customers list
                del self.active_customers[visitor_id]
                # Trigger a quick dummy event to keep loop running seamlessly
                return self.next_event()


def post_batch(api_url: str, events: list) -> bool:
    try:
        r = httpx.post(f"{api_url}/events/ingest", json={"events": events}, timeout=5)
        if r.status_code in (200, 201, 207):
            res = r.json()
            print_success(f"Ingested batch of {len(events)} events | Accepted={res.get('accepted', 0)} Rejected={res.get('rejected', 0)} Duplicates={res.get('duplicate', 0)}")
            return True
        else:
            print_error(f"Failed to post to API. Status code: {r.status_code} | Details: {r.text}")
            return False
    except Exception as e:
        print_error(f"Ingest endpoint unreachable: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Live Stream Event Simulator")
    parser.add_argument("--api-url", default="http://localhost:8000", help="FastAPI Base URL")
    parser.add_argument("--file", help="Path to a JSONL file to replay")
    parser.add_argument("--speed", type=float, default=1.0, help="Simulation speed multiplier")
    parser.add_argument("--store", default="STORE_BLR_001", help="Store ID to simulate/filter")
    parser.add_argument("--batch-size", type=int, default=1, help="Ingest batch size")
    
    args = parser.parse_args()
    
    print_info(f"Starting simulation. Target API: {args.api_url}")
    print_info(f"Store Filter: {args.store} | Speed multiplier: {args.speed}x")
    
    # ── Option A: Replay JSONL file chronologically ─────────────────────────
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print_error(f"Replay file does not exist: {file_path}")
            sys.exit(1)
            
        print_info(f"Replaying JSONL events from file: {file_path}")
        events = []
        with open(file_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue
                        
        if not events:
            print_error("No valid events found in JSONL file.")
            sys.exit(1)
            
        # Sort chronologically by ISO timestamp or ts if available
        def get_ts(ev):
            if "ts" in ev:
                return float(ev["ts"])
            iso_str = ev.get("timestamp", "")
            try:
                return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0
                
        events.sort(key=get_ts)
        print_info(f"Loaded and sorted {len(events)} events.")
        
        batch = []
        last_ts = None
        for ev in events:
            # Overwrite store_id to match filter if desired
            ev["store_id"] = args.store
            
            curr_ts = get_ts(ev)
            if last_ts is not None and args.speed > 0:
                delay = (curr_ts - last_ts) / args.speed
                if delay > 0:
                    time.sleep(min(delay, 5.0)) # Clamp sleep to max 5s for smooth simulation
                    
            last_ts = curr_ts
            batch.append(ev)
            
            # Print feedback
            print_info(f"Sending event: {ev['event_type']} | Visitor: {ev['visitor_id']} | Zone: {ev.get('zone_id')}")
            
            if len(batch) >= args.batch_size:
                post_batch(args.api_url, batch)
                batch = []
                
        if batch:
            post_batch(args.api_url, batch)
            
        print_success("Completed replaying file. Exiting.")
        
    # ── Option B: Continuous live synthetic stream ───────────────────────────
    else:
        print_info("No input file specified. Initiating continuous synthetic live stream...")
        gen = EventGenerator(store_id=args.store)
        
        batch = []
        while True:
            try:
                ev = gen.next_event()
                # Print visual logging indicator
                zone_str = f"({ev['zone_id']})" if ev.get('zone_id') else ""
                staff_str = " [STAFF]" if ev.get('is_staff') else ""
                print(f"\033[90m[{datetime.now().strftime('%H:%M:%S')}]\033[0m Replaying: {ev['event_type']:<20} | Visitor: {ev['visitor_id']:<12} {zone_str:<12} {staff_str}")
                
                batch.append(ev)
                
                if len(batch) >= args.batch_size:
                    post_batch(args.api_url, batch)
                    batch = []
                
                # Sleep between events
                sleep_time = random.uniform(1.5, 4.0) / args.speed
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                print_warning("Simulation stopped by user. Exiting.")
                break
            except Exception as e:
                print_error(f"Simulator loop error: {e}")
                time.sleep(2)


if __name__ == "__main__":
    main()
