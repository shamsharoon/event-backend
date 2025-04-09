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
            
            # Generate available time slots (9 AM to 5 PM, hourly slots)
            all_slots = []
            for day in range(days_ahead):
                date = now + timedelta(days=day)
                # Skip weekends (5=Saturday, 6=Sunday)
                if date.weekday() >= 5:
                    continue
                
                # Generate slots for 9 AM to 5 PM with 30-min intervals for more flexibility
                # Instead of using UTC timezone, generate slots in local timezone
                for hour in range(9, 17):  # End at 4:30 PM for 1-hour slots
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
            
            # Sort slots by date/time
            all_slots.sort()
            
            # Use up to 15 available slots
            available_slots = all_slots[:15]
            
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
            available_slots = [
                (now + timedelta(days=1, hours=10)).isoformat(),
                (now + timedelta(days=1, hours=14)).isoformat(),
                (now + timedelta(days=2, hours=9)).isoformat(),
                (now + timedelta(days=2, hours=13)).isoformat(),
                (now + timedelta(days=2, hours=16)).isoformat(),
            ]
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

@app.get("/session/clear")
async def clear_session(request: Request):
    """Completely clear the session for testing"""
    request.session.clear()
    return {"status": "success", "message": "Session cleared"}
