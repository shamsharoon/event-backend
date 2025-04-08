# auth.py
import os
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
import google_auth_oauthlib.flow

# Allow OAuth2 to work with HTTP for local development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

router = APIRouter()

# Path to your client secrets JSON downloaded from GCP
CLIENT_SECRETS_FILE = "./client_secret.json"

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',  # adjust as necessary
          'https://www.googleapis.com/auth/calendar.events']  # if writing events

@router.get("/auth")
async def authorize():
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES)
    flow.redirect_uri = "http://localhost:8000/auth/callback"
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    # You might want to store the 'state' in session for security verification
    return RedirectResponse(url=authorization_url)

@router.get("/auth/callback")
async def oauth2_callback(request: Request):
    state = request.query_params.get("state")
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state)
    flow.redirect_uri = "http://localhost:8000/auth/callback"

    authorization_response = str(request.url)
    flow.fetch_token(authorization_response=authorization_response)

    credentials = flow.credentials

    # Save these credentials securely (e.g., in a session or DB)
    # For demonstration, you can return a success message
    return {"status": "Authentication successful", "token": credentials.token}
