# auth.py
import os
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
import google_auth_oauthlib.flow
from starlette.responses import HTMLResponse

# Allow OAuth2 to work with HTTP for local development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

router = APIRouter()

# Path to your client secrets JSON downloaded from GCP
CLIENT_SECRETS_FILE = "./client_secret.json"

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',  # adjust as necessary
          'https://www.googleapis.com/auth/calendar.events']  # if writing events

@router.get("/auth")
async def authorize(request: Request):
    """Start the OAuth flow to authenticate with Google"""
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES)
    flow.redirect_uri = "http://localhost:8000/auth/callback"
    
    # Store the state in the session for security
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    request.session["state"] = state
    
    # Redirect to Google's OAuth page
    return RedirectResponse(url=authorization_url)

@router.get("/auth/callback")
async def oauth2_callback(request: Request):
    """Handle the OAuth callback from Google"""
    # Get the authorization code and state from the request
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    
    # Verify state matches what we stored (CSRF protection)
    if state != request.session.get("state"):
        return HTMLResponse("<h1>Invalid state parameter. Authentication failed.</h1>")
    
    # Exchange the authorization code for credentials
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state)
    flow.redirect_uri = "http://localhost:8000/auth/callback"

    try:
        flow.fetch_token(code=code)

        # Store credentials in the session
        credentials = flow.credentials
        request.session["credentials"] = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        
        # Return HTML that closes the popup and reloads the parent window
        return HTMLResponse("""
            <html>
            <head>
                <title>Authentication Successful</title>
                <script>
                    window.onload = function() {
                        if (window.opener) {
                            window.opener.location.reload();
                            window.close();
                        } else {
                            window.location.href = "http://localhost:5173";
                        }
                    }
                </script>
            </head>
            <body>
                <h1>Authentication Successful!</h1>
                <p>You can close this window now.</p>
            </body>
            </html>
        """)
    except Exception as e:
        print(f"Error fetching token: {e}")
        return HTMLResponse(f"<h1>Authentication failed</h1><p>Error details: {str(e)}</p>")

@router.get("/auth/logout")
async def logout(request: Request):
    """Clear the user's session"""
    try:
        # Clear credentials from session
        if "credentials" in request.session:
            del request.session["credentials"]
            
        # Clear state if it exists
        if "state" in request.session:
            del request.session["state"]
            
        return {"status": "success", "message": "Successfully logged out"}
    except Exception as e:
        print(f"Error during logout: {e}")
        return {"status": "error", "message": str(e)}
