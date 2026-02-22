"""
Cliente de Gmail usando la API oficial con OAuth2.
Soporta autenticación desde dict (multi-usuario con DB).
"""
import base64
import json
import re
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

import config


def _get_header(headers: list, name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _decode_body(payload: dict) -> str:
    """Extrae el texto plano del cuerpo de un mensaje de Gmail."""
    if payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in parts:
        result = _decode_body(part)
        if result:
            return result

    return ""


def _clean_text(text: str) -> str:
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class GmailClient:
    def __init__(self):
        self.service = None
        self.creds = None

    def authenticate_from_dict(self, creds_data: dict) -> bool:
        """Autentica con credenciales desde un dict (almacenado cifrado en DB)."""
        import os
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

        try:
            creds = Credentials.from_authorized_user_info(creds_data, config.GMAIL_SCOPES)
        except Exception:
            creds = Credentials.from_authorized_user_info(creds_data)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                return False

        self.creds = creds
        self.service = build("gmail", "v1", credentials=creds)
        return True

    def get_credentials_dict(self) -> dict:
        """Retorna las credenciales actuales como dict para guardar en DB."""
        if not self.creds:
            return {}
        return json.loads(self.creds.to_json())

    @staticmethod
    def create_auth_flow(redirect_uri: str) -> Flow:
        flow = Flow.from_client_secrets_file(
            str(config.GMAIL_CREDENTIALS_FILE),
            scopes=config.GMAIL_SCOPES,
            redirect_uri=redirect_uri,
        )
        return flow

    def authenticate_with_code(self, flow: Flow, code: str, code_verifier: str = None) -> dict:
        """Completa la autenticación. Retorna dict de credenciales para DB."""
        import os
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        kwargs = {"code": code}
        if code_verifier:
            kwargs["code_verifier"] = code_verifier
        flow.fetch_token(**kwargs)
        self.creds = flow.credentials
        self.service = build("gmail", "v1", credentials=self.creds)
        return self.get_credentials_dict()

    def get_unread_emails(self, max_results: int = None) -> list[dict]:
        if not self.service:
            return []

        max_results = max_results or config.MAX_EMAILS_TO_FETCH

        results = self.service.users().messages().list(
            userId="me", q="is:unread", maxResults=max_results,
        ).execute()

        messages = results.get("messages", [])
        emails = []

        for msg_meta in messages:
            msg = self.service.users().messages().get(
                userId="me", id=msg_meta["id"], format="full"
            ).execute()

            headers = msg.get("payload", {}).get("headers", [])
            body = _clean_text(_decode_body(msg.get("payload", {})))
            date_str = _get_header(headers, "Date")

            try:
                date = parsedate_to_datetime(date_str)
            except Exception:
                date = None

            emails.append({
                "id": msg_meta["id"],
                "source": "Gmail",
                "from": _get_header(headers, "From"),
                "subject": _get_header(headers, "Subject"),
                "date": date,
                "date_str": date_str,
                "snippet": msg.get("snippet", ""),
                "body": body[:5000],
            })

        return emails

    def get_email_by_id(self, email_id: str) -> dict | None:
        if not self.service:
            return None

        msg = self.service.users().messages().get(
            userId="me", id=email_id, format="full"
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        body = _clean_text(_decode_body(msg.get("payload", {})))
        date_str = _get_header(headers, "Date")

        try:
            date = parsedate_to_datetime(date_str)
        except Exception:
            date = None

        return {
            "id": email_id,
            "source": "Gmail",
            "from": _get_header(headers, "From"),
            "subject": _get_header(headers, "Subject"),
            "date": date,
            "date_str": date_str,
            "body": body,
        }

    def mark_as_read(self, email_id: str) -> bool:
        if not self.service:
            return False
        self.service.users().messages().modify(
            userId="me", id=email_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        return True

    def archive(self, email_id: str) -> bool:
        if not self.service:
            return False
        self.service.users().messages().modify(
            userId="me", id=email_id, body={"removeLabelIds": ["INBOX", "UNREAD"]}
        ).execute()
        return True

    def send_email(self, to: str, subject: str, body: str, reply_to_id: str = None) -> bool:
        if not self.service:
            return False

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_body = {"raw": raw}

        if reply_to_id:
            original = self.service.users().messages().get(
                userId="me", id=reply_to_id, format="metadata"
            ).execute()
            send_body["threadId"] = original.get("threadId")

        self.service.users().messages().send(userId="me", body=send_body).execute()
        return True
