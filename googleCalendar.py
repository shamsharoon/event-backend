# googleCalendar.py
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
import json
from datetime import datetime, timedelta

def build_credentials(session_creds):
    """Rebuild Google OAuth2 credentials from session data"""
    return Credentials(
        token=session_creds.get("token"),
        refresh_token=session_creds.get("refresh_token"),
        token_uri=session_creds.get("token_uri"),
        client_id=session_creds.get("client_id"),
        client_secret=session_creds.get("client_secret"),
        scopes=session_creds.get("scopes")
    )

def get_calendar_events(credentials, time_min, time_max):
    """Get calendar events in the specified time range"""
    try:
        # If we received session credentials dict, rebuild proper credentials
        if isinstance(credentials, dict):
            credentials = build_credentials(credentials)
            
        service = build('calendar', 'v3', credentials=credentials)
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except HttpError as error:
        print(f'An error occurred: {error}')
        raise
    except Exception as e:
        print(f'Unexpected error: {e}')
        raise

def get_freebusy_data(credentials, time_min, time_max):
    """Get free/busy data for the specified time range"""
    try:
        # If we received session credentials dict, rebuild proper credentials
        if isinstance(credentials, dict):
            credentials = build_credentials(credentials)
            
        service = build('calendar', 'v3', credentials=credentials)
        
        # Request free/busy information from all calendars
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [
                {"id": "primary"},  # Primary calendar
                # Add more calendars as needed - could fetch user's calendar list first
            ],
            "timeZone": "UTC"
        }
        
        freebusy_result = service.freebusy().query(body=body).execute()
        
        # Combine busy periods from all calendars
        all_busy = []
        for calendar_id, calendar_data in freebusy_result.get('calendars', {}).items():
            busy_periods = calendar_data.get('busy', [])
            all_busy.extend(busy_periods)
            
        # Sort busy periods by start time
        all_busy.sort(key=lambda x: x['start'])
        
        # Merge overlapping busy periods
        merged_busy = []
        for busy in all_busy:
            if not merged_busy or busy['start'] > merged_busy[-1]['end']:
                merged_busy.append(busy)
            else:
                merged_busy[-1]['end'] = max(merged_busy[-1]['end'], busy['end'])
                
        return {'busy': merged_busy}
    
    except HttpError as error:
        print(f'An error occurred: {error}')
        raise
    except Exception as e:
        print(f'Unexpected error: {e}')
        raise

def create_calendar_event(credentials, event_data):
    """Create a new event in the user's primary calendar"""
    try:
        # If we received session credentials dict, rebuild proper credentials
        if isinstance(credentials, dict):
            credentials = build_credentials(credentials)
            
        service = build('calendar', 'v3', credentials=credentials)
        event = service.events().insert(
            calendarId='primary',
            body=event_data
        ).execute()
        return event
    except HttpError as error:
        print(f'An error occurred: {error}')
        raise
    except Exception as e:
        print(f'Unexpected error: {e}')
        raise

# For testing when real auth isn't available
def mock_freebusy_data(time_min, time_max):
    """Generate mock busy times for testing"""
    # Parse the time range
    start_time = datetime.fromisoformat(time_min.replace('Z', '+00:00'))
    end_time = datetime.fromisoformat(time_max.replace('Z', '+00:00'))
    
    # Create some mock busy periods
    busy_periods = []
    
    # Create a busy period for each day from 12-1 PM (lunch)
    current = start_time
    while current < end_time:
        # Add a lunch meeting
        lunch_start = datetime(
            current.year, current.month, current.day, 
            12, 0, tzinfo=current.tzinfo
        )
        lunch_end = lunch_start + timedelta(hours=1)
        
        if lunch_start >= start_time and lunch_end <= end_time:
            busy_periods.append({
                'start': lunch_start.isoformat(),
                'end': lunch_end.isoformat()
            })
        
        # Add a random meeting in the afternoon
        meeting_start = datetime(
            current.year, current.month, current.day, 
            15, 0, tzinfo=current.tzinfo
        )
        meeting_end = meeting_start + timedelta(hours=1)
        
        if meeting_start >= start_time and meeting_end <= end_time:
            busy_periods.append({
                'start': meeting_start.isoformat(),
                'end': meeting_end.isoformat()
            })
        
        # Move to next day
        current += timedelta(days=1)
    
    return {'busy': busy_periods}

