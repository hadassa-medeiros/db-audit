from pathlib import Path

from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

READ = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
WRITE = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
RAIZ = Path(__file__).resolve().parent.parent


def get_creds(write=False):
    scopes = WRITE if write else READ
    config_path = RAIZ / "config" / "oauth_client.json"
    token_path = RAIZ / "config" / ("token_write.json" if write else "token_readonly.json")
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(config_path), scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return creds


def connect(write=False):
    drive = build("drive", "v3", credentials=get_creds(write))
    email = drive.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    print(f"Conectada como {email} ({'escrita' if write else 'só leitura'})")
    return drive

def connect_sheets():
    return build("sheets", "v4", credentials=get_creds(write=True))