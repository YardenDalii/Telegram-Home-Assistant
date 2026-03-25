"""iCloud CalDAV client.

Provides connection testing, calendar listing, event creation, and event fetching.
All event creation uses manually-built iCal strings with UTC Z-suffix timestamps —
this exact format is confirmed to work with iCloud's CalDAV server.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from utils.logger import get_logger

logger = get_logger(__name__)

_ICLOUD_URL = "https://caldav.icloud.com"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_principal(username: str, password: str):
    """Authenticate and return the CalDAV principal object."""
    import caldav
    client = caldav.DAVClient(url=_ICLOUD_URL, username=username, password=password)
    return client.principal()


def _to_utc_naive(dt: datetime) -> datetime:
    """Convert any datetime to a naive UTC datetime.

    Naive input is treated as local system time (correct when the bot runs in the
    user's timezone, e.g. Israel Standard/Daylight time on the Raspberry Pi).
    """
    if dt.tzinfo is None:
        # Attach the system's local timezone, then convert to UTC
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _extract_ical_field(ical_data: str, field: str) -> str | None:
    """Return the value of the first matching iCal field, or None."""
    for line in ical_data.splitlines():
        if line.startswith(f"{field}:") or line.startswith(f"{field};"):
            colon = line.index(":")
            return line[colon + 1:].strip()
    return None


def _event_calendars(principal) -> list:
    """Return only calendars that support VEVENT (not task/reminder collections).

    iCloud exposes both calendar (VEVENT) and reminders (VTODO) collections via
    CalDAV.  principal.calendars() returns all of them.  If we save a VEVENT to a
    VTODO-only collection CalDAV accepts the PUT (201) but the event never appears
    in Calendar.app.  This helper filters to VEVENT-capable collections only.
    """
    result = []
    for cal in principal.calendars():
        try:
            supported = cal.get_supported_components()
            if supported and "VEVENT" not in supported:
                logger.debug(f"Skipping non-VEVENT calendar: {cal.name!r} ({supported})")
                continue
        except Exception:
            pass  # if we can't check, include the calendar
        result.append(cal)
    return result or principal.calendars()  # fallback: return all if filtering left nothing


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def test_connection(username: str, password: str) -> bool:
    """Return True if credentials are valid and iCloud CalDAV is reachable."""
    try:
        _get_principal(username, password)
        return True
    except Exception as exc:
        logger.debug(f"CalDAV test_connection failed: {exc}")
        return False


def list_calendars(username: str, password: str) -> list[str]:
    """Return a list of calendar display names for the user's account."""
    try:
        principal = _get_principal(username, password)
        return [c.name for c in _event_calendars(principal) if c.name]
    except Exception as exc:
        logger.error(f"list_calendars failed: {exc}", exc_info=True)
        return []


def create_event(
    username: str,
    password: str,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    calendar_name: str | None = None,
) -> str | None:
    """Create a calendar event on iCloud.

    Returns the name of the calendar the event was saved to, or None on failure.
    """
    try:
        principal = _get_principal(username, password)
        calendars = _event_calendars(principal)
        if not calendars:
            logger.warning("create_event: no VEVENT-capable calendars found on this account")
            return None

        # Pick the target calendar
        target = calendars[0]
        if calendar_name:
            name_lower = calendar_name.strip().lower()
            match = next(
                (c for c in calendars if name_lower in (c.name or "").lower()),
                None,
            )
            if match:
                target = match
        logger.info(f"create_event: targeting calendar '{target.name}' (url={target.url})")

        # Build iCal — UTC Z-suffix timestamps, no VTIMEZONE (iCloud-compatible)
        start_utc = _to_utc_naive(start_dt)
        end_utc   = _to_utc_naive(end_dt)
        now_utc   = datetime.now(timezone.utc).replace(tzinfo=None)
        uid       = f"{uuid.uuid4()}@homebot"

        ical = (
            "BEGIN:VCALENDAR\r\n"
            "PRODID:-//Home Bot//EN\r\n"
            "VERSION:2.0\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{now_utc.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"SUMMARY:{title}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

        target.save_event(ical)
        logger.info(f"create_event: saved '{title}' to calendar '{target.name}'")

        # Warm iCloud's server-side cache: a REPORT request immediately after a write
        # forces iCloud to flush pending writes so the next read sees the new event.
        try:
            target.date_search(start=start_utc, end=end_utc, expand=True)
        except Exception:
            pass  # Non-critical — event was written successfully

        return target.name

    except Exception as exc:
        logger.error(f"create_event failed: {exc}", exc_info=True)
        return None


def get_events_for_date(
    username: str, password: str, target_date: date
) -> list[dict]:
    """Return all events on a specific date."""
    return get_events_for_range(username, password, target_date, target_date)


def get_events_for_range(
    username: str, password: str, start_date: date, end_date: date
) -> list[dict]:
    """Return all events between start_date and end_date (inclusive)."""
    try:
        principal = _get_principal(username, password)
        search_start = datetime(start_date.year, start_date.month, start_date.day)
        search_end   = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)

        events: list[dict] = []
        for cal in _event_calendars(principal):
            try:
                for ev in cal.date_search(start=search_start, end=search_end, expand=True):
                    data = ev.data or ""
                    title   = _extract_ical_field(data, "SUMMARY") or "(ללא כותרת)"
                    dtstart = _extract_ical_field(data, "DTSTART") or ""
                    all_day = len(dtstart.replace("VALUE=DATE:", "").strip()) == 8

                    start_parsed: datetime | None = None
                    event_date: date | None = None
                    if all_day and dtstart:
                        raw_d = dtstart.split(":")[-1].strip()[:8]
                        try:
                            event_date = date(int(raw_d[:4]), int(raw_d[4:6]), int(raw_d[6:8]))
                        except ValueError:
                            pass
                    elif dtstart:
                        raw = dtstart.split(":")[-1].strip()
                        for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
                            try:
                                start_parsed = datetime.strptime(raw[:15], fmt[:len(raw[:15])])
                                break
                            except ValueError:
                                continue
                        if start_parsed:
                            event_date = start_parsed.date()

                    events.append({
                        "title":    title,
                        "start":    start_parsed,
                        "all_day":  all_day,
                        "calendar": cal.name,
                        "date":     event_date,
                    })
            except Exception:
                pass  # Skip calendars that fail to fetch

        events.sort(key=lambda e: (e["start"] or datetime.min))
        return events

    except Exception as exc:
        logger.error(f"get_events_for_range failed: {exc}", exc_info=True)
        return []
