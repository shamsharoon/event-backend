# main.py
from fastapi import FastAPI, Depends
from auth import router as auth_router
from googleCalendar import get_calendar_events, get_freebusy_data
from scheduler import rank_time_slots
from datetime import datetime, timedelta

app = FastAPI()
app.include_router(auth_router)

@app.get("/schedule")
async def get_schedule():
    # In practice, retrieve and validate OAuth credentials
    credentials = ...  # Fetch stored credentials for the user

    # Define time window (e.g., next 7 days)
    now = datetime.utcnow().isoformat() + "Z"
    later = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

    # Fetch events and freebusy data
    events = get_calendar_events(credentials, now, later)
    freebusy = get_freebusy_data(credentials, now, later)

    # Compute available slots (this is simplified; you’ll need to write logic that
    # subtracts busy times from your defined working hours)
    available_slots = ["2025-04-09T10:00:00Z", "2025-04-09T14:00:00Z", "2025-04-09T16:00:00Z"]

    # Get AI recommendations
    ai_recommendations = rank_time_slots(available_slots, context_info={"events": events})
    return {"available_slots": available_slots, "recommendations": ai_recommendations}
