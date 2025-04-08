# googleCalendar.py
from googleapiclient.discovery import build

def get_calendar_events(credentials, time_min, time_max):
    service = build('calendar', 'v3', credentials=credentials)
    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    return events_result.get('items', [])

# calendar.py continued
def get_freebusy_data(credentials, time_min, time_max):
    service = build('calendar', 'v3', credentials=credentials)
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": "primary"}]
    }
    freebusy_result = service.freebusy().query(body=body).execute()
    return freebusy_result.get('calendars', {}).get('primary', {})

