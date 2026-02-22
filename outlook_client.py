"""
Cliente de Outlook/Hotmail usando Microsoft Graph API con MSAL OAuth2.
Soporta token cache en memoria (multi-usuario con DB).
"""
import re
from datetime import datetime

import msal
import requests

import config

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"


class OutlookClient:
    def __init__(self):
        self.access_token = None
        self._app = None
        self._cache = msal.SerializableTokenCache()

    def _get_msal_app(self) -> msal.PublicClientApplication:
        if self._app:
            return self._app

        self._app = msal.PublicClientApplication(
            client_id=config.OUTLOOK_CLIENT_ID,
            authority=config.OUTLOOK_AUTHORITY,
            token_cache=self._cache,
        )
        return self._app

    def get_token_cache_data(self) -> str:
        """Retorna el token cache serializado para guardar en DB."""
        return self._cache.serialize()

    def authenticate_from_cache_data(self, cache_data: str) -> bool:
        """Autentica desde token cache serializado (de DB)."""
        if not config.OUTLOOK_CLIENT_ID or not cache_data:
            return False
        self._cache.deserialize(cache_data)
        app = self._get_msal_app()
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(config.OUTLOOK_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self.access_token = result["access_token"]
                return True
        return False

    def start_device_flow(self) -> dict | None:
        if not config.OUTLOOK_CLIENT_ID:
            return None
        app = self._get_msal_app()
        flow = app.initiate_device_flow(scopes=config.OUTLOOK_SCOPES)
        if "user_code" not in flow:
            return None
        return flow

    def complete_device_flow(self, flow: dict) -> bool:
        app = self._get_msal_app()
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            self.access_token = result["access_token"]
            return True
        return False

    def _make_request(self, url: str, params: dict = None) -> dict | None:
        if not self.access_token:
            return None

        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 401:
            # Try to refresh token
            app = self._get_msal_app()
            accounts = app.get_accounts()
            if accounts:
                result = app.acquire_token_silent(config.OUTLOOK_SCOPES, account=accounts[0])
                if result and "access_token" in result:
                    self.access_token = result["access_token"]
                    headers = {"Authorization": f"Bearer {self.access_token}"}
                    response = requests.get(url, headers=headers, params=params)
                else:
                    return None
            else:
                return None

        if response.status_code != 200:
            return None

        return response.json()

    def get_unread_emails(self, max_results: int = None) -> list[dict]:
        max_results = max_results or config.MAX_EMAILS_TO_FETCH

        url = f"{GRAPH_ENDPOINT}/me/mailFolders/inbox/messages"
        params = {
            "$filter": "isRead eq false",
            "$top": max_results,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,body",
            "$orderby": "receivedDateTime desc",
        }

        data = self._make_request(url, params)
        if not data:
            return []

        emails = []
        for msg in data.get("value", []):
            from_info = msg.get("from", {}).get("emailAddress", {})
            from_str = f"{from_info.get('name', '')} <{from_info.get('address', '')}>"

            date_str = msg.get("receivedDateTime", "")
            try:
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except Exception:
                date = None

            body_text = msg.get("body", {}).get("content", "")
            if msg.get("body", {}).get("contentType") == "html":
                body_text = re.sub(r'<style[^>]*>.*?</style>', '', body_text, flags=re.DOTALL)
                body_text = re.sub(r'<[^>]+>', ' ', body_text)
                body_text = re.sub(r'\s+', ' ', body_text).strip()

            emails.append({
                "id": msg["id"],
                "source": "Outlook",
                "from": from_str,
                "subject": msg.get("subject", "(Sin asunto)"),
                "date": date,
                "date_str": date_str,
                "snippet": msg.get("bodyPreview", ""),
                "body": body_text[:5000],
            })

        return emails

    def get_email_by_id(self, email_id: str) -> dict | None:
        url = f"{GRAPH_ENDPOINT}/me/messages/{email_id}"
        params = {"$select": "id,subject,from,receivedDateTime,body"}

        data = self._make_request(url, params)
        if not data:
            return None

        from_info = data.get("from", {}).get("emailAddress", {})
        from_str = f"{from_info.get('name', '')} <{from_info.get('address', '')}>"

        date_str = data.get("receivedDateTime", "")
        try:
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            date = None

        body_text = data.get("body", {}).get("content", "")
        if data.get("body", {}).get("contentType") == "html":
            body_text = re.sub(r'<style[^>]*>.*?</style>', '', body_text, flags=re.DOTALL)
            body_text = re.sub(r'<[^>]+>', ' ', body_text)
            body_text = re.sub(r'\s+', ' ', body_text).strip()

        return {
            "id": email_id,
            "source": "Outlook",
            "from": from_str,
            "subject": data.get("subject", "(Sin asunto)"),
            "date": date,
            "date_str": date_str,
            "body": body_text,
        }

    def mark_as_read(self, email_id: str) -> bool:
        if not self.access_token:
            return False
        url = f"{GRAPH_ENDPOINT}/me/messages/{email_id}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        response = requests.patch(url, headers=headers, json={"isRead": True})
        return response.status_code == 200

    def archive(self, email_id: str) -> bool:
        if not self.access_token:
            return False
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        requests.patch(
            f"{GRAPH_ENDPOINT}/me/messages/{email_id}",
            headers=headers, json={"isRead": True}
        )
        response = requests.post(
            f"{GRAPH_ENDPOINT}/me/messages/{email_id}/move",
            headers=headers, json={"destinationId": "archive"}
        )
        return response.status_code in (200, 201)

    def send_email(self, to: str, subject: str, body: str, reply_to_id: str = None) -> bool:
        if not self.access_token:
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        if reply_to_id:
            url = f"{GRAPH_ENDPOINT}/me/messages/{reply_to_id}/reply"
            payload = {"comment": body}
            response = requests.post(url, headers=headers, json=payload)
            return response.status_code == 202
        else:
            url = f"{GRAPH_ENDPOINT}/me/sendMail"
            payload = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                }
            }
            response = requests.post(url, headers=headers, json=payload)
            return response.status_code == 202
