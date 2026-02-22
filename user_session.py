"""
Estado de email por usuario en memoria.
Cada usuario autenticado tiene su propia instancia de UserEmailSession.
"""
import json
import time

import config
from gmail_client import GmailClient
from outlook_client import OutlookClient
from imap_client import ImapClient
from models import db, EmailAccount, AnalysisCache
from token_encryption import encrypt_token, decrypt_token

EMAIL_CACHE_TTL = 300  # 5 minutos


class UserEmailSession:
    """Encapsula todo el estado de email de un solo usuario."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.gmail_client: GmailClient | None = None
        self.gmail_connected: bool = False
        self.outlook_client: OutlookClient | None = None
        self.outlook_connected: bool = False
        self.imap_clients: dict[str, ImapClient] = {}
        self.imap_connected: dict[str, bool] = {}

        # In-memory caches
        self._email_cache: dict[str, dict] = {}
        self._email_list_cache: list[dict] = []
        self._email_list_timestamp: float = 0
        self._email_list_source: str = "all"

    # --- Sources ---

    def get_sources(self) -> list[dict]:
        sources = []
        if self.gmail_connected:
            sources.append({"name": "Gmail", "key": "gmail", "type": "gmail", "connected": True})
        if self.outlook_connected:
            sources.append({"name": "Outlook", "key": "outlook", "type": "outlook", "connected": True})
        for name, connected in self.imap_connected.items():
            if connected:
                sources.append({"name": name, "key": name, "type": "imap", "connected": True})
        return sources

    # --- Restore connections from DB ---

    def restore_connections(self):
        """Lee email_accounts de la DB y reconecta clientes."""
        accounts = EmailAccount.query.filter_by(user_id=self.user_id, connected=True).all()
        for acct in accounts:
            try:
                creds = decrypt_token(acct.encrypted_credentials)
                if acct.provider == "gmail":
                    self._restore_gmail(creds)
                elif acct.provider == "outlook":
                    self._restore_outlook(creds)
                elif acct.provider == "imap":
                    self._restore_imap(acct.name, creds)
            except Exception as e:
                print(f"[!] Error restaurando {acct.provider} ({acct.name}) para user {self.user_id}: {e}")

    def _restore_gmail(self, creds_data: dict):
        client = GmailClient()
        if client.authenticate_from_dict(creds_data):
            self.gmail_client = client
            self.gmail_connected = True
            print(f"[OK] Gmail restaurado para user {self.user_id}")

    def _restore_outlook(self, creds_data: dict):
        client = OutlookClient()
        if client.authenticate_from_cache_data(creds_data.get("token_cache", "")):
            self.outlook_client = client
            self.outlook_connected = True
            print(f"[OK] Outlook restaurado para user {self.user_id}")

    def _restore_imap(self, name: str, creds_data: dict):
        client = ImapClient(
            name=name,
            host=creds_data["host"],
            port=creds_data.get("port", 993),
            email_addr=creds_data["email"],
            password=creds_data["password"],
            smtp_host=creds_data.get("smtp_host", ""),
            smtp_port=creds_data.get("smtp_port", 587),
        )
        if client.authenticate():
            self.imap_clients[name] = client
            self.imap_connected[name] = True
            print(f"[OK] IMAP ({name}) restaurado para user {self.user_id}")

    # --- Save/remove accounts in DB ---

    def save_gmail_credentials(self, creds_dict: dict):
        """Guarda credenciales Gmail cifradas en DB."""
        encrypted = encrypt_token(creds_dict)
        acct = EmailAccount.query.filter_by(
            user_id=self.user_id, provider="gmail"
        ).first()
        if acct:
            acct.encrypted_credentials = encrypted
            acct.connected = True
        else:
            acct = EmailAccount(
                user_id=self.user_id, provider="gmail", name="Gmail",
                encrypted_credentials=encrypted, connected=True,
            )
            db.session.add(acct)
        db.session.commit()

    def save_outlook_credentials(self, cache_data: str):
        """Guarda token cache de Outlook cifrado en DB."""
        encrypted = encrypt_token({"token_cache": cache_data})
        acct = EmailAccount.query.filter_by(
            user_id=self.user_id, provider="outlook"
        ).first()
        if acct:
            acct.encrypted_credentials = encrypted
            acct.connected = True
        else:
            acct = EmailAccount(
                user_id=self.user_id, provider="outlook", name="Outlook",
                encrypted_credentials=encrypted, connected=True,
            )
            db.session.add(acct)
        db.session.commit()

    def save_imap_credentials(self, name: str, creds_data: dict):
        """Guarda credenciales IMAP cifradas en DB."""
        encrypted = encrypt_token(creds_data)
        acct = EmailAccount(
            user_id=self.user_id, provider="imap", name=name,
            encrypted_credentials=encrypted, connected=True,
        )
        db.session.add(acct)
        db.session.commit()

    def disconnect_account(self, provider: str, name: str = None):
        """Elimina una cuenta de email de la DB y limpia estado en memoria."""
        query = EmailAccount.query.filter_by(user_id=self.user_id, provider=provider)
        if name:
            query = query.filter_by(name=name)
        query.delete()
        db.session.commit()

        if provider == "gmail":
            self.gmail_client = None
            self.gmail_connected = False
        elif provider == "outlook":
            self.outlook_client = None
            self.outlook_connected = False
        elif provider == "imap" and name:
            self.imap_clients.pop(name, None)
            self.imap_connected.pop(name, None)

    # --- Fetch emails ---

    def _fetch_from_sources(self, source_filter: str) -> list[dict]:
        all_emails = []

        if source_filter in ("all", "gmail") and self.gmail_connected and self.gmail_client:
            try:
                all_emails.extend(self.gmail_client.get_unread_emails())
            except Exception as e:
                print(f"[!] Error fetching Gmail for user {self.user_id}: {e}")

        if source_filter in ("all", "outlook") and self.outlook_connected and self.outlook_client:
            try:
                all_emails.extend(self.outlook_client.get_unread_emails())
            except Exception as e:
                print(f"[!] Error fetching Outlook for user {self.user_id}: {e}")

        for name, client in self.imap_clients.items():
            if source_filter not in ("all", name):
                continue
            if not self.imap_connected.get(name):
                continue
            try:
                all_emails.extend(client.get_unread_emails())
            except Exception as e:
                print(f"[!] Error fetching IMAP ({name}) for user {self.user_id}: {e}")

        all_emails.sort(key=lambda e: e.get("date") or "", reverse=True)
        return all_emails

    def fetch_all_emails(self, source_filter: str = "all", force: bool = False) -> list[dict]:
        now = time.time()
        cache_valid = (
            not force
            and self._email_list_cache
            and self._email_list_source == source_filter
            and (now - self._email_list_timestamp) < EMAIL_CACHE_TTL
        )
        if cache_valid:
            return self._email_list_cache

        all_emails = self._fetch_from_sources(source_filter)
        for em in all_emails:
            key = f"{em['source']}:{em['id']}"
            self._email_cache[key] = em

        self._email_list_cache = all_emails
        self._email_list_timestamp = now
        self._email_list_source = source_filter
        return all_emails

    def refresh_emails(self, source_filter: str = "all") -> dict:
        old_ids = {em["id"] for em in self._email_list_cache}
        new_list = self.fetch_all_emails(source_filter, force=True)
        new_ids = {em["id"] for em in new_list}
        return {
            "total": len(new_list),
            "new_count": len(new_ids - old_ids),
            "removed_count": len(old_ids - new_ids),
            "new_ids": list(new_ids - old_ids),
        }

    def get_cached_email(self, source: str, email_id: str) -> dict | None:
        key = f"{source}:{email_id}"
        if key in self._email_cache:
            return self._email_cache[key]

        em = None
        if source == "Gmail" and self.gmail_connected and self.gmail_client:
            em = self.gmail_client.get_email_by_id(email_id)
        elif source == "Outlook" and self.outlook_connected and self.outlook_client:
            em = self.outlook_client.get_email_by_id(email_id)
        elif source in self.imap_clients and self.imap_connected.get(source):
            em = self.imap_clients[source].get_email_by_id(email_id)

        if em:
            self._email_cache[key] = em
        return em

    def mark_email_as_read(self, source: str, email_id: str) -> bool:
        try:
            success = False
            if source == "Gmail" and self.gmail_connected and self.gmail_client:
                success = self.gmail_client.mark_as_read(email_id)
            elif source == "Outlook" and self.outlook_connected and self.outlook_client:
                success = self.outlook_client.mark_as_read(email_id)
            elif source in self.imap_clients and self.imap_connected.get(source):
                success = self.imap_clients[source].mark_as_read(email_id)
            if success:
                self._email_list_timestamp = 0
            return success
        except Exception as e:
            print(f"[!] Error marking as read: {e}")
        return False

    def archive_email(self, source: str, email_id: str) -> bool:
        try:
            success = False
            if source == "Gmail" and self.gmail_connected and self.gmail_client:
                success = self.gmail_client.archive(email_id)
            elif source == "Outlook" and self.outlook_connected and self.outlook_client:
                success = self.outlook_client.archive(email_id)
            elif source in self.imap_clients and self.imap_connected.get(source):
                success = self.imap_clients[source].archive(email_id)
            if success:
                self._email_list_timestamp = 0
            return success
        except Exception as e:
            print(f"[!] Error archiving: {e}")
        return False

    def send_reply(self, source: str, email_id: str, to: str, subject: str, body: str) -> bool:
        try:
            if source == "Gmail" and self.gmail_connected and self.gmail_client:
                return self.gmail_client.send_email(to, subject, body, reply_to_id=email_id)
            elif source == "Outlook" and self.outlook_connected and self.outlook_client:
                return self.outlook_client.send_email(to, subject, body, reply_to_id=email_id)
            elif source in self.imap_clients and self.imap_connected.get(source):
                return self.imap_clients[source].send_email(to, subject, body, reply_to_id=email_id)
        except Exception as e:
            print(f"[!] Error sending reply: {e}")
        return False

    # --- Analysis cache (DB-backed) ---

    def get_analysis(self, email_id: str) -> dict | None:
        entry = AnalysisCache.query.filter_by(
            user_id=self.user_id, email_id=email_id
        ).first()
        if entry:
            return json.loads(entry.result_json)
        return None

    def set_analysis(self, email_id: str, source: str, result: dict):
        entry = AnalysisCache.query.filter_by(
            user_id=self.user_id, email_id=email_id
        ).first()
        result_json = json.dumps(result, ensure_ascii=False)
        if entry:
            entry.result_json = result_json
        else:
            entry = AnalysisCache(
                user_id=self.user_id, email_id=email_id,
                source=source, result_json=result_json,
            )
            db.session.add(entry)
        db.session.commit()

    def get_all_analysis(self) -> dict:
        entries = AnalysisCache.query.filter_by(user_id=self.user_id).all()
        return {e.email_id: json.loads(e.result_json) for e in entries}


# --- Global session store ---
_sessions: dict[int, UserEmailSession] = {}


def get_user_session(user_id: int) -> UserEmailSession:
    """Obtiene o crea la sesión de email de un usuario."""
    if user_id not in _sessions:
        _sessions[user_id] = UserEmailSession(user_id)
    return _sessions[user_id]


def remove_user_session(user_id: int):
    """Limpia la sesión de email al hacer logout."""
    _sessions.pop(user_id, None)
