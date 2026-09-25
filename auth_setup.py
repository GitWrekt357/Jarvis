from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os

# Read-only scope — matches the "just report on my calendar" scope for now.
# If you later add event creation, change this to:
# "https://www.googleapis.com/auth/calendar"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def get_credentials():
    creds = None

    # If we already have a token, reuse/refresh it instead of re-authenticating
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # No valid token yet, or it's expired with no refresh token available
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the token for next time
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


if __name__ == "__main__":
    creds = get_credentials()
    print("Auth successful. Token saved to", TOKEN_FILE)
