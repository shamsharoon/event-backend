# scheduler.py
import openai

def rank_time_slots(available_slots, context_info):
    prompt = (
        "Given the following available time slots: " +
        f"{available_slots}. Considering the user's past scheduling patterns, "
        "meeting fatigue, and time-of-day preferences, rank the best three slots "
        "for booking a new event. Provide a short explanation for each suggestion."
    )
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=prompt,
        max_tokens=150,
        n=1,
        stop=None,
        temperature=0.7,
    )
    suggestions = response.choices[0].text.strip()
    return suggestions
