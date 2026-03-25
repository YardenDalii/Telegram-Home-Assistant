"""Standalone test for iCloud CalDAV integration.

Run from project root (venv activated):
    python scripts/test_calendar.py

Reads ICLOUD_EMAIL and ICLOUD_PASSWORD from .env, or set them manually below.
Creates a test event, verifies it appears, then deletes it.
"""

import sys
import os
import time
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

# Allow importing from src/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

EMAIL    = os.getenv("ICLOUD_EMAIL", "")
PASSWORD = os.getenv("ICLOUD_PASSWORD", "")

if not EMAIL or not PASSWORD:
    print("Set ICLOUD_EMAIL and ICLOUD_PASSWORD in your .env (or edit this script).")
    sys.exit(1)

# ── import the actual module being tested ────────────────────────────────────
from cal.apple_cal import (
    test_connection,
    list_calendars,
    create_event,
    get_events_for_date,
)

PASSES = 0
FAILS  = 0

def ok(msg):  global PASSES; PASSES += 1; print(f"  ✅ {msg}")
def fail(msg): global FAILS;  FAILS  += 1; print(f"  ❌ {msg}")


# ── 1. Connection ─────────────────────────────────────────────────────────────
print("\n[1] Testing connection...")
if test_connection(EMAIL, PASSWORD):
    ok("Connected to iCloud CalDAV")
else:
    fail("Could not connect — check credentials")
    sys.exit(1)


# ── 2. Calendar list ──────────────────────────────────────────────────────────
print("\n[2] Listing calendars...")
cals = list_calendars(EMAIL, PASSWORD)
if cals:
    ok(f"Found {len(cals)} calendar(s):")
    for c in cals:
        print(f"       • {c}")
else:
    fail("No calendars returned")
    sys.exit(1)


# ── 3 × create + verify ───────────────────────────────────────────────────────
TARGET_CAL = cals[0]  # use the first calendar returned
print(f"\n[3] Running 3 create-and-verify cycles on calendar: '{TARGET_CAL}'")

today = date.today()
test_date = today + timedelta(days=1)  # tomorrow

for i in range(1, 4):
    title = f"Bot Test Event {i} — {datetime.now().strftime('%H:%M:%S')}"
    start = datetime(test_date.year, test_date.month, test_date.day, 10 + i, 0)
    end   = start + timedelta(hours=1)

    print(f"\n  Cycle {i}: '{title}'")

    # Create
    cal_used = create_event(EMAIL, PASSWORD, title, start, end, TARGET_CAL)
    if not cal_used:
        fail(f"create_event returned None")
        continue
    ok(f"create_event → '{cal_used}'")

    # Wait for iCloud to sync before verifying
    print(f"       Waiting 10s for iCloud to sync...")
    time.sleep(10)

    # Verify
    events = get_events_for_date(EMAIL, PASSWORD, test_date)
    match = next((e for e in events if title in e["title"]), None)
    if match:
        ok(f"Event found via get_events_for_date ✓")
    else:
        fail(f"Event NOT found in get_events_for_date — created but not readable back")
        print(f"       Events returned: {[e['title'] for e in events]}")

    if i < 3:
        print(f"       Pausing 5s before next cycle...")
        time.sleep(5)


# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Results: {PASSES} passed, {FAILS} failed")
if FAILS == 0:
    print("All tests passed — calendar integration is working correctly.")
else:
    print("Some tests failed — check the output above for details.")
