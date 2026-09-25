from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import os

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_FILE = "token.json"


def _get_calendar_service():
    """Loads the saved token, refreshes it if needed, and returns a Calendar API client."""
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_upcoming_events(time_range="today", max_results=10):
    """
    Fetches upcoming calendar events for the given time range.

    time_range: "today", "tomorrow", or "week"
    Returns a simplified list of dicts: summary, start, location
    """
    service = _get_calendar_service()

    now = datetime.now(timezone.utc)

    if time_range == "today":
        time_min = now
        time_max = now.replace(hour=23, minute=59, second=59)
    elif time_range == "tomorrow":
        tomorrow = now + timedelta(days=1)
        time_min = tomorrow.replace(hour=0, minute=0, second=0)
        time_max = tomorrow.replace(hour=23, minute=59, second=59)
    elif time_range == "week":
        time_min = now
        time_max = now + timedelta(days=7)
    else:
        time_min = now
        time_max = now + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min.isoformat(),
        timeMax=time_max.isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])

    simplified = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        simplified.append({
            "summary": event.get("summary", "(No title)"),
            "start": start,
            "location": event.get("location", ""),
        })

    return simplified

calendar_tool_schema = {
    "name": "get_upcoming_events",
    "description": "Get the user's upcoming calendar events for a given time range.",
    "input_schema": {
        "type": "object",
        "properties": {
            "time_range": {
                "type": "string",
                "enum": ["today", "tomorrow", "week"],
                "description": "The time range to fetch events for."
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return.",
                "default": 10
            }
        },
        "required": ["time_range"]
    }
}

if __name__ == "__main__":
    # Quick manual test
    results = get_upcoming_events("today")
    for e in results:
        print(f"{e['start']} — {e['summary']}")
