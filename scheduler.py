import os
from datetime import datetime

def rank_time_slots(available_slots, context_info):
    """Rank time slots based on context info"""
    if not available_slots:
        return "No slots available for ranking."
    
    # Parse preferred times from context
    prefers_morning = "morning" in context_info.lower()
    prefers_afternoon = "afternoon" in context_info.lower()
    
    # Find preferred weekday if mentioned
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
    preferred_day = None
    for day in weekdays:
        if day in context_info.lower():
            preferred_day = day
            break
    
    # Score each available slot
    scored_slots = []
    for slot in available_slots:
        try:
            dt = datetime.fromisoformat(slot.replace('Z', '+00:00'))
            score = 0
            
            # Weekday preference
            if preferred_day and dt.strftime('%A').lower() == preferred_day:
                score += 10
            
            # Time of day preference
            hour = dt.hour
            if prefers_morning and 9 <= hour <= 12:
                score += 5
            elif prefers_afternoon and 13 <= hour <= 17:
                score += 5
            
            # Prefer times not too early or too late
            if 10 <= hour <= 15:  # 10 AM to 3 PM is generally good
                score += 3
                
            scored_slots.append((slot, score))
            
        except Exception:
            # Skip slots with parsing issues
            continue
    
    # Sort by score (descending)
    scored_slots.sort(key=lambda x: x[1], reverse=True)
    
    # Format the top 3 or fewer recommendations
    top_slots = scored_slots[:min(3, len(scored_slots))]
    
    if not top_slots:
        return "No suitable slots found based on your preferences."
    
    # Build the recommendation text
    result = "Based on your scheduling patterns, here are the recommended slots:\n\n"
    
    for i, (slot, score) in enumerate(top_slots, 1):
        dt = datetime.fromisoformat(slot.replace('Z', '+00:00'))
        formatted_time = dt.strftime("%A, %B %d at %I:%M %p")
        result += f"{i}. {formatted_time}\n"
    
    return result
