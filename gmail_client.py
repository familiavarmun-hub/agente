"""
Cliente de Gmail usando la API oficial con OAuth2.
"""
import base64
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

    # Buscar recursivamente en partes anidadas
    for part in parts:
        result = _decode_body(part)
        if result:
            return result

    return ""


def _clean_text(text: str) -> str:
    """Limpia el texto del correo eliminando exceso de espacios y líneas vacías."""
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class GmailClient:
    def __init__(self):
        self.service = None
        self.creds = None

    def authenticate(self) -> bool:
        """Intenta autenticar con token existente/refrescado. Retorna True si exitoso."""
        import os
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

        creds = None

        if config.GMAIL_TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(config.GMAIL_TOKEN_FILE), config.GMAIL_SCOPES
                )
            except Exception:
                # Token con scopes incompatibles, cargar sin restricción
                creds = Credentials.from_authorized_user_file(
                    str(config.GMAIL_TOKEN_FILE)
                )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                return False  # Necesita OAuth web flow

            config.GMAIL_TOKEN_FILE.write_text(creds.to_json())

        self.creds = creds
        self.service = build("gmail", "v1", credentials=creds)
        return True

    @staticmethod
    def create_auth_flow(redirect_uri: str) -> Flow:
        """Crea el flujo OAuth para autenticación web."""
        flow = Flow.from_client_secrets_file(
            str(config.GMAIL_CREDENTIALS_FILE),
            scopes=config.GMAIL_SCOPES,
            redirect_uri=redirect_uri,
        )
        return flow

    def authenticate_with_code(self, flow: Flow, code: str) -> bool:
        """Completa la autenticación con el código de autorización del callback."""
        import os
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        flow.fetch_token(code=code)
        self.creds = flow.credentials
        config.GMAIL_TOKEN_FILE.write_text(self.creds.to_json())
        self.service = build("gmail", "v1", credentials=self.creds)
        return True

    def get_unread_emails(self, max_results: int = None) -> list[dict]:
        """Obtiene los correos no leídos del buzón."""
        if not self.service:
            return []

        max_results = max_results or config.MAX_EMAILS_TO_FETCH

        results = self.service.users().messages().list(
            userId="me",
            q="is:unread",
            maxResults=max_results,
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
        """Obtiene un correo específico por su ID."""
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
        """Marca un email como leído removiendo la etiqueta UNREAD."""
        if not self.service:
            return False
        self.service.users().messages().modify(
            userId="me", id=email_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        return True

    def archive(self, email_id: str) -> bool:
        """Archiva un email removiendo la etiqueta INBOX."""
        if not self.service:
            return False
        self.service.users().messages().modify(
            userId="me", id=email_id,
            body={"removeLabelIds": ["INBOX", "UNREAD"]}
        ).execute()
        return True

    def send_email(self, to: str, subject: str, body: str, reply_to_id: str = None) -> bool:
        """Envía un email o respuesta vía Gmail API."""
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
