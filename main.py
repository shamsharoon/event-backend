# main.py
from fastapi import FastAPI, Depends, HTTPException, Request, status
from auth import router as auth_router
from googleCalendar import get_calendar_events, get_freebusy_data, create_calendar_event, mock_freebusy_data
from scheduler import rank_time_slots
from datetime import datetime, timedelta, timezone
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer
import json
import os
from starlette.middleware.sessions import SessionMiddleware
import re

app = FastAPI()
app.include_router(auth_router)

# Session middleware for storing auth state
app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here")  # Use a strong secret in production

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EventCreate(BaseModel):
    start_time: str
    summary: str
    description: Optional[str] = None

class NaturalLanguageCommand(BaseModel):
    command: str

# Mock credentials for development - in production use proper auth flow
class MockCredentials:
    def __init__(self, token="mock_token"):
        self.token = token

# Update the get_credentials function
def get_credentials(request: Request):
    """Get credentials from session or return mock credentials"""
    credentials = request.session.get("credentials")
    if not credentials:
        return None
    
    # Return the credentials dictionary from session
    return credentials

@app.get("/auth/status")
async def auth_status(request: Request):
    """Check if the user is authenticated with Google Calendar"""
    credentials = request.session.get("credentials")
    return {"authenticated": credentials is not None}

@app.get("/schedule")
async def get_schedule(request: Request, days_ahead: Optional[int] = 7):
    try:
        # Time range for availability check (next 7 days by default)
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()
        
        # Get credentials from session
        credentials = get_credentials(request)
        use_real_calendar = credentials is not None and "token" in credentials
        
        try:
            # Use real calendar data if we have valid credentials
            if use_real_calendar:
                # Get actual free/busy data from Google Calendar API
                freebusy_data = get_freebusy_data(credentials, time_min, time_max)
                busy_periods = freebusy_data.get('busy', [])
                
                # Log the API response for debugging
                print("\n===== GOOGLE CALENDAR API RESPONSE =====")
                print(f"Time range: {time_min} to {time_max}")
                print(f"Freebusy data: {json.dumps(freebusy_data, indent=2)}")
                print(f"Number of busy periods: {len(busy_periods)}")
                for i, busy in enumerate(busy_periods[:5]):  # Log first 5 busy periods
                    print(f"Busy period {i+1}: {busy.get('start')} to {busy.get('end')}")
                print("=======================================\n")
                
                # Get the user's calendar information for better recommendations
                calendar_events = get_calendar_events(credentials, time_min, time_max)
                
                # Extract event metadata for better contextual recommendations
                event_patterns = analyze_event_patterns(calendar_events)
                context_info = f"User has {len(calendar_events)} events scheduled. " + event_patterns
            else:
                # Use mock data for development without real auth
                freebusy_data = mock_freebusy_data(time_min, time_max)
                busy_periods = freebusy_data.get('busy', [])
                context_info = "User prefers afternoon meetings on Tuesdays and morning meetings on Thursdays."
            
            # Generate available time slots (9 AM to 7 PM, hourly slots)
            all_slots = []
            # Track available weekend slots for debugging
            weekend_slots = []
            
            for day in range(days_ahead):
                date = now + timedelta(days=day)
                # Include all days including weekends
                is_weekend = date.weekday() >= 5  # 5=Saturday, 6=Sunday
                
                # Generate slots for 9 AM to 7 PM with 30-min intervals for more flexibility
                for hour in range(9, 19):  # End at 6:30 PM for 1-hour slots
                    for minute in [0, 30]:  # Add 30-minute intervals
                        # Create slot in UTC time but representing local office hours (9-5)
                        slot_time = datetime(
                            date.year, date.month, date.day, 
                            hour, minute, tzinfo=timezone.utc
                        )
                        
                        # Skip slots in the past
                        if slot_time <= now:
                            continue
                            
                        # Format as ISO string - includes timezone info with Z suffix
                        slot_str = slot_time.isoformat()
                        
                        # Check if slot conflicts with busy periods
                        is_available = True
                        for busy in busy_periods:
                            # Make sure both times have proper timezone information
                            busy_start = busy['start']
                            busy_end = busy['end']
                            
                            # Ensure we have timezone info - use UTC (Z) if none provided
                            if 'Z' not in busy_start and '+' not in busy_start and '-' not in busy_start:
                                busy_start = busy_start + 'Z'
                            if 'Z' not in busy_end and '+' not in busy_end and '-' not in busy_end:
                                busy_end = busy_end + 'Z'
                                
                            # Parse to datetime objects with timezone
                            busy_start = datetime.fromisoformat(busy_start.replace('Z', '+00:00'))
                            busy_end = datetime.fromisoformat(busy_end.replace('Z', '+00:00'))
                            
                            # 1-hour slots, so check if any part overlaps with busy period
                            slot_end = slot_time + timedelta(hours=1)
                            
                            # If slot overlaps with busy period, mark as unavailable
                            if (busy_start <= slot_time < busy_end) or \
                               (busy_start < slot_end <= busy_end) or \
                               (slot_time <= busy_start and slot_end >= busy_end):
                                is_available = False
                                break
                        
                        if is_available:
                            all_slots.append(slot_str)
                            # Track weekend slots separately for debugging
                            if is_weekend:
                                weekend_slots.append(slot_str)
            
            # Sort slots by date/time
            all_slots.sort()
            
            # Log weekend slots for debugging
            print("\n===== AVAILABLE WEEKEND SLOTS =====")
            print(f"Total weekend slots found: {len(weekend_slots)}")
            for i, slot in enumerate(weekend_slots[:10]):  # Log up to 10 weekend slots
                slot_dt = datetime.fromisoformat(slot.replace('Z', '+00:00'))
                print(f"Weekend slot {i+1}: {slot_dt.strftime('%A, %Y-%m-%d %H:%M')}")
            print("=================================\n")
            
            # Log all slots for debugging
            print(f"Total available slots: {len(all_slots)}")
            print(f"First 5 available slots: {all_slots[:5]}")
            
            # Return all available slots, not just 15
            available_slots = all_slots
            
            # Generate smart recommendations based on the calendar data
            recommended_slots = get_recommended_slots(available_slots, context_info)
            
            # Include note about data source
            response_data = {
                "available_slots": available_slots,
                "recommendations": recommended_slots
            }
            
            if not use_real_calendar:
                response_data["note"] = "Using mock calendar data. Connect with Google for real availability."
                
            return response_data
            
        except Exception as calendar_err:
            # Fallback to mock data if calendar integration fails
            print(f"Google Calendar integration failed: {str(calendar_err)}")
            # Mock data as fallback
            # Calculate some dates including weekends
            current_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            # Get next Saturday
            days_until_saturday = (5 - current_date.weekday()) % 7
            if days_until_saturday == 0:
                days_until_saturday = 7  # If today is Saturday, get next Saturday
            next_saturday = current_date + timedelta(days=days_until_saturday)
            # Get next Sunday
            next_sunday = next_saturday + timedelta(days=1)
            
            available_slots = [
                (now + timedelta(days=1, hours=10)).isoformat(),  # Weekday
                (now + timedelta(days=1, hours=14)).isoformat(),  # Weekday
                (now + timedelta(days=2, hours=9)).isoformat(),   # Weekday
                (now + timedelta(days=2, hours=13)).isoformat(),  # Weekday
                (next_saturday + timedelta(hours=10)).isoformat(),  # Saturday 10 AM
                (next_saturday + timedelta(hours=14)).isoformat(),  # Saturday 2 PM
                (next_sunday + timedelta(hours=12)).isoformat(),    # Sunday 12 PM
                (next_sunday + timedelta(hours=16)).isoformat(),    # Sunday 4 PM
            ]
            
            print("\n===== MOCK DATA INCLUDES WEEKEND SLOTS =====")
            print(f"Next Saturday: {next_saturday.isoformat()}")
            print(f"Next Sunday: {next_sunday.isoformat()}")
            for slot in available_slots:
                dt = datetime.fromisoformat(slot.replace('Z', '+00:00'))
                day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][dt.weekday()]
                print(f"Mock slot: {day_name}, {dt.isoformat()}")
            print("=========================================\n")
            
            recommendation = "Based on your calendar availability, these are the open slots in the next few days."
            
            return {
                "available_slots": available_slots,
                "recommendations": recommendation,
                "note": "Using fallback data due to calendar integration issues"
            }
            
    except Exception as e:
        # Proper FastAPI error handling
        print(f"Error in get_schedule: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process schedule: {str(e)}")

# Helper functions for analyzing calendar patterns
def analyze_event_patterns(calendar_events):
    """Extract patterns from calendar events to provide context for recommendations"""
    if not calendar_events:
        return "No existing events found to analyze patterns."
        
    # Count events by day of week
    weekday_counts = [0] * 7  # Monday to Sunday
    hour_counts = [0] * 24  # 0-23 hours
    
    for event in calendar_events:
        try:
            start = event.get('start', {})
            if 'dateTime' in start:
                start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                weekday = start_time.weekday()
                hour = start_time.hour
                
                weekday_counts[weekday] += 1
                hour_counts[hour] += 1
        except (ValueError, KeyError):
            continue
    
    # Find preferred days and times
    max_weekday = weekday_counts.index(max(weekday_counts))
    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    preferred_day = weekdays[max_weekday]
    
    # Check if mornings or afternoons are preferred
    morning_count = sum(hour_counts[9:12])  # 9 AM to 12 PM
    afternoon_count = sum(hour_counts[13:17])  # 1 PM to 5 PM
    time_preference = "mornings" if morning_count > afternoon_count else "afternoons"
    
    return f"User typically schedules meetings on {preferred_day} and prefers {time_preference}."

def get_recommended_slots(available_slots, context_info):
    """Get recommended slots based on availability and context"""
    if not available_slots:
        return "No available slots found in the specified time range."
        
    # Simple recommendation without AI - based on context info
    if "mornings" in context_info.lower():
        # Filter morning slots (before noon)
        morning_slots = [slot for slot in available_slots if datetime.fromisoformat(slot.replace('Z', '+00:00')).hour < 12]
        if morning_slots:
            formatted_slots = [format_slot_for_display(slot) for slot in morning_slots[:3]]
            return f"Based on your calendar patterns, you seem to prefer morning meetings. Here are some recommended morning slots:\n" + "\n".join(formatted_slots)
    
    if "afternoons" in context_info.lower():
        # Filter afternoon slots (after noon)
        afternoon_slots = [slot for slot in available_slots if datetime.fromisoformat(slot.replace('Z', '+00:00')).hour >= 12]
        if afternoon_slots:
            formatted_slots = [format_slot_for_display(slot) for slot in afternoon_slots[:3]]
            return f"Based on your calendar patterns, you seem to prefer afternoon meetings. Here are some recommended afternoon slots:\n" + "\n".join(formatted_slots)
    
    # Default recommendation - first 3 available slots
    formatted_slots = [format_slot_for_display(slot) for slot in available_slots[:3]]
    return f"Here are the most optimal slots based on your calendar:\n" + "\n".join(formatted_slots)

def format_slot_for_display(slot_iso):
    """Format ISO slot time for display in recommendations"""
    dt = datetime.fromisoformat(slot_iso.replace('Z', '+00:00'))
    return dt.strftime("%A, %B %d at %I:%M %p")

@app.post("/schedule/create")
async def create_event(request: Request, event: EventCreate):
    """Create a new event in Google Calendar"""
    credentials = request.session.get("credentials")
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated with Google Calendar"
        )
    
    try:
        # Parse start time - keep the timezone information intact
        start_time = event.start_time
        
        # If the start_time has no timezone info, assume UTC
        if 'Z' not in start_time and '+' not in start_time and '-' not in start_time:
            start_time += 'Z'
            
        # Parse to datetime to add an hour
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = start_dt + timedelta(minutes=60)  # Default 1 hour event
        
        # Create event using ISO format strings with timezone information
        event_details = {
            "summary": event.summary,
            "description": event.description or "",
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_dt.isoformat().replace('+00:00', 'Z')},
        }
        
        result = create_calendar_event(credentials, event_details)
        return {"status": "success", "event_id": result.get("id")}
        
    except Exception as e:
        print(f"Error creating event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create event: {str(e)}")

@app.post("/schedule/process-command")
async def process_command(request: Request, command_request: NaturalLanguageCommand):
    """Process natural language scheduling commands"""
    credentials = request.session.get("credentials")
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated with Google Calendar"
        )
        
    try:
        command = command_request.command.lower()
        
        # Get current available slots
        now = datetime.now(timezone.utc)
        time_max = (now + timedelta(days=14)).isoformat()
        
        # Get actual free/busy data from Google Calendar API
        freebusy_data = get_freebusy_data(credentials, now.isoformat(), time_max)
        busy_periods = freebusy_data.get('busy', [])
        
        # Extract potential date and time from command
        event_name, event_date, event_time, description = extract_event_info(command)
        
        # Generate all available slots
        available_slots = generate_available_slots(now, 14, busy_periods)
        
        # Find matching slots
        matching_slots = find_matching_slots(available_slots, event_date, event_time)
        
        if matching_slots:
            best_slot = matching_slots[0]
            slot_dt = datetime.fromisoformat(best_slot.replace('Z', '+00:00'))
            
            friendly_date = slot_dt.strftime("%A, %B %d at %I:%M %p")
            print(f"Debug - Found slot: {best_slot}")
            print(f"Debug - Event name: {event_name}")
            print(f"Debug - Date components: Y={slot_dt.year} M={slot_dt.month} D={slot_dt.day}")
            
            return {
                "found_slot": best_slot,
                "event_name": event_name,
                "event_description": description,
                "message": f"Found a slot for '{event_name}' on {friendly_date}. Click 'Schedule Event' to confirm."
            }
        else:
            return {
                "found_slot": None,
                "event_name": event_name,
                "event_description": description,
                "message": f"Could not find an available slot for '{event_name}' on the requested date/time. Please select a date and time manually."
            }
            
    except Exception as e:
        print(f"Error processing command: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process command: {str(e)}")

def extract_event_info(command):
    """Extract event name, date, time, and description from command"""
    # Default values
    event_name = None
    event_date = None
    event_time = None
    description = None
    
    # Extract event name (simplistic approach - first part of the command)
    name_match = re.search(r'schedule\s+(?:an?|the)\s+(.+?)(?:\s+on\s+|\s+at\s+|\s+for\s+|$)', command)
    if name_match:
        event_name = name_match.group(1).strip()
    else:
        # Fallback - take everything after "schedule"
        name_match = re.search(r'schedule\s+(.+?)(?:\s+on\s+|\s+at\s+|\s+for\s+|$)', command)
        if name_match:
            event_name = name_match.group(1).strip()
    
    # Extract date
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    day_pattern = '|'.join(days)
    
    date_match = re.search(f'(?:on|this|next)\\s+({day_pattern})', command)
    if date_match:
        day_name = date_match.group(1).lower()
        day_index = days.index(day_name)
        
        # Calculate date
        today = datetime.now()
        current_day_idx = today.weekday()  # 0 = Monday, 6 = Sunday
        
        if "next" in command:
            # Next week's day
            days_ahead = (day_index - current_day_idx) % 7 + 7
        else:
            # This week's day
            days_ahead = (day_index - current_day_idx) % 7
            
            # If it's today or in the past, assume next week
            if days_ahead == 0 and "today" not in command:
                days_ahead = 7
                
        target_date = today + timedelta(days=days_ahead)
        event_date = {
            'year': target_date.year,
            'month': target_date.month,
            'day': target_date.day
        }
    
    # Extract time
    time_match = re.search(r'at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', command)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        am_pm = time_match.group(3)
        
        # Convert to 24-hour format
        if am_pm:
            if am_pm.lower() == 'pm' and hour < 12:
                hour += 12
            elif am_pm.lower() == 'am' and hour == 12:
                hour = 0
        elif hour < 8:  # Assume PM for ambiguous times (e.g., "at 5")
            hour += 12
            
        event_time = {'hour': hour, 'minute': minute}
    
    # Extract description (anything after "for" or "to")
    desc_match = re.search(r'(?:for|to)\s+(.+?)$', command)
    if desc_match:
        description = desc_match.group(1).strip()
    
    return event_name, event_date, event_time, description

def generate_available_slots(start_date, days_ahead, busy_periods):
    """Generate available time slots based on busy periods"""
    available_slots = []
    
    for day in range(days_ahead):
        date = start_date + timedelta(days=day)
        # Include all days including weekends
        
        # Generate slots for 9 AM to 7 PM with 30-min intervals for more flexibility
        for hour in range(9, 19):  # End at 6:30 PM for 1-hour slots
            for minute in [0, 30]:  # Add 30-minute intervals
                slot_time = datetime(
                    date.year, date.month, date.day, 
                    hour, minute, tzinfo=timezone.utc
                )
                
                # Skip slots in the past
                if slot_time <= start_date:
                    continue
                
                # Check if slot conflicts with busy periods
                is_available = True
                for busy in busy_periods:
                    # Make sure both times have proper timezone information
                    busy_start = busy['start'] 
                    busy_end = busy['end']
                    
                    # Ensure we have timezone info - use UTC (Z) if none provided
                    if 'Z' not in busy_start and '+' not in busy_start and '-' not in busy_start:
                        busy_start = busy_start + 'Z'
                    if 'Z' not in busy_end and '+' not in busy_end and '-' not in busy_end:
                        busy_end = busy_end + 'Z'
                        
                    # Parse to datetime objects with timezone
                    busy_start = datetime.fromisoformat(busy_start.replace('Z', '+00:00'))
                    busy_end = datetime.fromisoformat(busy_end.replace('Z', '+00:00'))
                    
                    # 1-hour slots, so check if any part overlaps with busy period
                    slot_end = slot_time + timedelta(hours=1)
                    
                    # If slot overlaps with busy period, mark as unavailable
                    if (busy_start <= slot_time < busy_end) or \
                       (busy_start < slot_end <= busy_end) or \
                       (slot_time <= busy_start and slot_end >= busy_end):
                        is_available = False
                        break
                
                if is_available:
                    available_slots.append(slot_time.isoformat())
    
    return available_slots

def find_matching_slots(available_slots, event_date, event_time):
    """Find slots that match the requested date and time"""
    if not available_slots:
        return []
        
    matching_slots = []
    
    for slot in available_slots:
        slot_dt = datetime.fromisoformat(slot.replace('Z', '+00:00'))
        
        # Check if date matches
        date_matches = True
        if event_date:
            if (slot_dt.year != event_date['year'] or 
                slot_dt.month != event_date['month'] or 
                slot_dt.day != event_date['day']):
                date_matches = False
        
        # Check if time matches (within 1 hour)
        time_matches = True
        if event_time and date_matches:
            hour_diff = abs(slot_dt.hour - event_time['hour'])
            
            # Check if the time is within 2 hours of requested time
            if hour_diff > 2:
                time_matches = False
                
            # If minutes are specified, check them too (within 30 min)
            if 'minute' in event_time and abs(slot_dt.minute - event_time['minute']) > 30:
                time_matches = False
        
        if date_matches and time_matches:
            matching_slots.append(slot)
    
    return matching_slots

@app.get("/session/clear")
async def clear_session(request: Request):
    """Completely clear the session for testing"""
    request.session.clear()
    return {"status": "success", "message": "Session cleared"}
