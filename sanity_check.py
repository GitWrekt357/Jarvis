from google.oauth2.credentials import Credentials

creds = Credentials.from_authorized_user_file("token.json")
print("Valid:", creds.valid)
print("Scopes:", creds.scopes)
