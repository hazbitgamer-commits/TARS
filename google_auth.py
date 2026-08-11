"""Shared Google sign-in for the email and calendar skills.

Needs google_credentials.json (from the owner's Google Cloud setup) once; after the
first browser approval, google_token.json keeps it signed in.

Avast intercepts TLS on this PC, so we build a CA bundle that includes the
Windows certificate store and point both HTTP stacks at it.
"""
import os
import ssl
from pathlib import Path

BASE = Path(__file__).parent
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]
CRED = BASE / "google_credentials.json"
TOKEN = BASE / "google_token.json"
CA_BUNDLE = BASE / "ca_bundle.pem"


def _ca_bundle() -> str:
    if not CA_BUNDLE.exists():
        import certifi

        data = Path(certifi.where()).read_bytes()
        for store in ("ROOT", "CA"):
            for cert, enc, _ in ssl.enum_certificates(store):
                if enc == "x509_asn":
                    data += ssl.DER_cert_to_PEM_cert(cert).encode()
        CA_BUNDLE.write_bytes(data)
    return str(CA_BUNDLE)


def get_service(api: str, version: str):
    """Google API service, or None if the owner hasn't connected Google yet."""
    if not CRED.exists():
        return None
    bundle = _ca_bundle()
    os.environ["REQUESTS_CA_BUNDLE"] = bundle
    import httplib2.certs

    httplib2.certs.where = lambda: bundle

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_secrets_file(str(CRED), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build(api, version, credentials=creds, cache_discovery=False)
