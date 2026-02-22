"""
Cliente IMAP/SMTP genérico para cuentas de correo custom.
"""
import email
import imaplib
import smtplib
import re
from datetime import datetime
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

import config


def _decode_header_value(value: str) -> str:
    """Decodifica un header de email que puede estar codificado."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_text(msg: email.message.Message) -> str:
    """Extrae el texto plano del cuerpo de un email."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback: buscar HTML y limpiar
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    return re.sub(r'\s+', ' ', text).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


class ImapClient:
    def __init__(self, name: str, host: str, port: int, email_addr: str,
                 password: str, smtp_host: str = "", smtp_port: int = 587,
                 use_ssl: bool = True):
        self.name = name
        self.host = host
        self.port = port
        self.email_addr = email_addr
        self.password = password
        self.smtp_host = smtp_host or host
        self.smtp_port = smtp_port
        self.use_ssl = use_ssl
        self._conn: imaplib.IMAP4 | None = None

    def authenticate(self) -> bool:
        """Conecta al servidor IMAP y hace login."""
        try:
            if self.use_ssl:
                self._conn = imaplib.IMAP4_SSL(self.host, self.port)
            else:
                self._conn = imaplib.IMAP4(self.host, self.port)
            self._conn.login(self.email_addr, self.password)
            return True
        except Exception as e:
            print(f"[!] Error IMAP ({self.name}): {e}")
            self._conn = None
            return False

    def _ensure_connection(self) -> bool:
        """Reconecta si la conexión se perdió."""
        if self._conn is None:
            return self.authenticate()
        try:
            self._conn.noop()
            return True
        except Exception:
            return self.authenticate()

    def get_unread_emails(self, max_results: int = None) -> list[dict]:
        """Obtiene los correos no leídos."""
        if not self._ensure_connection():
            return []

        max_results = max_results or config.MAX_EMAILS_TO_FETCH

        try:
            self._conn.select("INBOX")
            _, data = self._conn.search(None, "UNSEEN")
            uids = data[0].split()

            # Tomar los más recientes
            uids = uids[-max_results:] if len(uids) > max_results else uids
            uids.reverse()  # Más recientes primero

            emails = []
            for uid in uids:
                _, msg_data = self._conn.fetch(uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_str = _decode_header_value(msg.get("From", ""))
                subject = _decode_header_value(msg.get("Subject", "(Sin asunto)"))
                date_str = msg.get("Date", "")
                body = _extract_text(msg)

                try:
                    date = parsedate_to_datetime(date_str)
                except Exception:
                    date = None

                emails.append({
                    "id": uid.decode(),
                    "source": self.name,
                    "from": from_str,
                    "subject": subject,
                    "date": date,
                    "date_str": date_str,
                    "snippet": body[:150].replace("\n", " "),
                    "body": body[:5000],
                })

            return emails
        except Exception as e:
            print(f"[!] Error fetching IMAP ({self.name}): {e}")
            return []

    def get_email_by_id(self, email_id: str) -> dict | None:
        """Obtiene un correo específico por su UID."""
        if not self._ensure_connection():
            return None

        try:
            self._conn.select("INBOX")
            _, msg_data = self._conn.fetch(email_id.encode(), "(RFC822)")
            if not msg_data or not msg_data[0]:
                return None

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            from_str = _decode_header_value(msg.get("From", ""))
            subject = _decode_header_value(msg.get("Subject", "(Sin asunto)"))
            date_str = msg.get("Date", "")
            body = _extract_text(msg)

            try:
                date = parsedate_to_datetime(date_str)
            except Exception:
                date = None

            return {
                "id": email_id,
                "source": self.name,
                "from": from_str,
                "subject": subject,
                "date": date,
                "date_str": date_str,
                "body": body,
            }
        except Exception as e:
            print(f"[!] Error fetching IMAP email ({self.name}): {e}")
            return None

    def mark_as_read(self, email_id: str) -> bool:
        """Marca un email como leído."""
        if not self._ensure_connection():
            return False
        try:
            self._conn.select("INBOX")
            self._conn.store(email_id.encode(), "+FLAGS", "\\Seen")
            return True
        except Exception as e:
            print(f"[!] Error marking as read IMAP ({self.name}): {e}")
            return False

    def archive(self, email_id: str) -> bool:
        """Archiva un email marcándolo como leído (IMAP no tiene carpeta Archive estándar)."""
        return self.mark_as_read(email_id)

    def send_email(self, to: str, subject: str, body: str, reply_to_id: str = None) -> bool:
        """Envía un email vía SMTP."""
        try:
            msg = MIMEText(body)
            msg["From"] = self.email_addr
            msg["To"] = to
            msg["Subject"] = subject

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_addr, self.password)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"[!] Error sending SMTP ({self.name}): {e}")
            return False
