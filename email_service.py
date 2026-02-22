"""
Capa de servicio que conecta Flask con los clientes de email.
Maneja singletons, caché de emails, caché de análisis IA y estado de conexión.
"""
import json
import time
from pathlib import Path

import config
from gmail_client import GmailClient
from outlook_client import OutlookClient
from imap_client import ImapClient

ANALYSIS_CACHE_FILE = Path(__file__).parent / "analysis_cache.json"

_gmail_client: GmailClient | None = None
_outlook_client: OutlookClient | None = None
_imap_clients: dict[str, ImapClient] = {}

_email_cache: dict[str, dict] = {}       # key = "source:id" → email dict
_email_list_cache: list[dict] = []        # lista ordenada de emails
_email_list_timestamp: float = 0          # cuándo se descargaron
_email_list_source: str = "all"           # filtro usado en última descarga

_analysis_cache: dict[str, dict] = {}

_gmail_connected: bool = False
_outlook_connected: bool = False
_imap_connected: dict[str, bool] = {}

EMAIL_CACHE_TTL = 300  # 5 minutos: no re-descargar si pasaron menos de 5 min


# --- Gmail ---

def get_gmail_client() -> GmailClient:
    global _gmail_client
    if _gmail_client is None:
        _gmail_client = GmailClient()
    return _gmail_client


def set_gmail_connected(val: bool):
    global _gmail_connected
    _gmail_connected = val


def is_gmail_connected() -> bool:
    return _gmail_connected


# --- Outlook ---

def get_outlook_client() -> OutlookClient:
    global _outlook_client
    if _outlook_client is None:
        _outlook_client = OutlookClient()
    return _outlook_client


def set_outlook_connected(val: bool):
    global _outlook_connected
    _outlook_connected = val


def is_outlook_connected() -> bool:
    return _outlook_connected


# --- IMAP ---

def init_imap_clients():
    for acct in config.IMAP_ACCOUNTS:
        name = acct.get("name", acct.get("email", "IMAP"))
        if name not in _imap_clients:
            _imap_clients[name] = ImapClient(
                name=name,
                host=acct["host"],
                port=acct.get("port", 993),
                email_addr=acct["email"],
                password=acct["password"],
                smtp_host=acct.get("smtp_host", ""),
                smtp_port=acct.get("smtp_port", 587),
            )


def add_imap_client(name: str, host: str, port: int, email_addr: str,
                    password: str, smtp_host: str, smtp_port: int) -> bool:
    client = ImapClient(name, host, port, email_addr, password, smtp_host, smtp_port)
    if client.authenticate():
        _imap_clients[name] = client
        _imap_connected[name] = True
        return True
    return False


def remove_imap_client(name: str):
    _imap_clients.pop(name, None)
    _imap_connected.pop(name, None)


def get_imap_clients() -> dict[str, ImapClient]:
    return _imap_clients


def get_imap_connected() -> dict[str, bool]:
    return dict(_imap_connected)


def get_all_sources() -> list[dict]:
    sources = []
    if _gmail_connected:
        sources.append({"name": "Gmail", "key": "gmail", "type": "gmail", "connected": True})
    if _outlook_connected:
        sources.append({"name": "Outlook", "key": "outlook", "type": "outlook", "connected": True})
    for name, connected in _imap_connected.items():
        if connected:
            sources.append({"name": name, "key": name, "type": "imap", "connected": True})
    return sources


# --- Análisis IA caché (persistente en disco) ---

def _load_analysis_cache():
    """Carga el caché de análisis desde disco al iniciar."""
    global _analysis_cache
    if ANALYSIS_CACHE_FILE.exists():
        try:
            _analysis_cache = json.loads(ANALYSIS_CACHE_FILE.read_text(encoding="utf-8"))
            print(f"[OK] Caché IA cargado: {len(_analysis_cache)} análisis previos.")
        except Exception:
            _analysis_cache = {}


def _save_analysis_cache():
    """Guarda el caché de análisis a disco."""
    try:
        ANALYSIS_CACHE_FILE.write_text(
            json.dumps(_analysis_cache, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[!] Error guardando caché IA: {e}")


def get_analysis(email_id: str) -> dict | None:
    return _analysis_cache.get(email_id)


def set_analysis(email_id: str, result: dict):
    _analysis_cache[email_id] = result
    _save_analysis_cache()


def get_all_analysis() -> dict:
    return dict(_analysis_cache)


# Cargar caché al importar el módulo
_load_analysis_cache()


# --- Emails ---

def _fetch_from_sources(source_filter: str) -> list[dict]:
    """Descarga emails frescos de las APIs (Gmail/Outlook/IMAP)."""
    all_emails = []

    if source_filter in ("all", "gmail") and _gmail_connected:
        try:
            all_emails.extend(get_gmail_client().get_unread_emails())
        except Exception as e:
            print(f"[!] Error fetching Gmail: {e}")

    if source_filter in ("all", "outlook") and _outlook_connected:
        try:
            all_emails.extend(get_outlook_client().get_unread_emails())
        except Exception as e:
            print(f"[!] Error fetching Outlook: {e}")

    for name, client in _imap_clients.items():
        if source_filter not in ("all", name):
            continue
        if not _imap_connected.get(name):
            continue
        try:
            all_emails.extend(client.get_unread_emails())
        except Exception as e:
            print(f"[!] Error fetching IMAP ({name}): {e}")

    all_emails.sort(key=lambda e: e.get("date") or "", reverse=True)
    return all_emails


def fetch_all_emails(source_filter: str = "all", force: bool = False) -> list[dict]:
    """Retorna emails, usando caché si están frescos (< 5 min)."""
    global _email_list_cache, _email_list_timestamp, _email_list_source

    now = time.time()
    cache_valid = (
        not force
        and _email_list_cache
        and _email_list_source == source_filter
        and (now - _email_list_timestamp) < EMAIL_CACHE_TTL
    )

    if cache_valid:
        return _email_list_cache

    # Descargar frescos
    all_emails = _fetch_from_sources(source_filter)

    # Actualizar caché
    for em in all_emails:
        key = f"{em['source']}:{em['id']}"
        _email_cache[key] = em

    _email_list_cache = all_emails
    _email_list_timestamp = now
    _email_list_source = source_filter

    return all_emails


def refresh_emails(source_filter: str = "all") -> dict:
    """Fuerza recarga y retorna info sobre emails nuevos vs anteriores."""
    old_ids = {em["id"] for em in _email_list_cache}

    new_list = fetch_all_emails(source_filter, force=True)
    new_ids = {em["id"] for em in new_list}

    added = new_ids - old_ids
    removed = old_ids - new_ids

    return {
        "total": len(new_list),
        "new_count": len(added),
        "removed_count": len(removed),
        "new_ids": list(added),
    }


def get_cached_email(source: str, email_id: str) -> dict | None:
    key = f"{source}:{email_id}"
    if key in _email_cache:
        return _email_cache[key]

    if source == "Gmail" and _gmail_connected:
        em = get_gmail_client().get_email_by_id(email_id)
    elif source == "Outlook" and _outlook_connected:
        em = get_outlook_client().get_email_by_id(email_id)
    elif source in _imap_clients and _imap_connected.get(source):
        em = _imap_clients[source].get_email_by_id(email_id)
    else:
        return None

    if em:
        _email_cache[key] = em
    return em


def _invalidate_email_list_cache():
    """Invalida el caché de la lista para que la próxima carga sea fresca."""
    global _email_list_timestamp
    _email_list_timestamp = 0


def mark_email_as_read(source: str, email_id: str) -> bool:
    try:
        success = False
        if source == "Gmail" and _gmail_connected:
            success = get_gmail_client().mark_as_read(email_id)
        elif source == "Outlook" and _outlook_connected:
            success = get_outlook_client().mark_as_read(email_id)
        elif source in _imap_clients and _imap_connected.get(source):
            success = _imap_clients[source].mark_as_read(email_id)
        if success:
            _invalidate_email_list_cache()
        return success
    except Exception as e:
        print(f"[!] Error marking as read: {e}")
    return False


def archive_email(source: str, email_id: str) -> bool:
    try:
        success = False
        if source == "Gmail" and _gmail_connected:
            success = get_gmail_client().archive(email_id)
        elif source == "Outlook" and _outlook_connected:
            success = get_outlook_client().archive(email_id)
        elif source in _imap_clients and _imap_connected.get(source):
            success = _imap_clients[source].archive(email_id)
        if success:
            _invalidate_email_list_cache()
        return success
    except Exception as e:
        print(f"[!] Error archiving: {e}")
    return False


def send_reply(source: str, email_id: str, to: str, subject: str, body: str) -> bool:
    try:
        if source == "Gmail" and _gmail_connected:
            return get_gmail_client().send_email(to, subject, body, reply_to_id=email_id)
        elif source == "Outlook" and _outlook_connected:
            return get_outlook_client().send_email(to, subject, body, reply_to_id=email_id)
        elif source in _imap_clients and _imap_connected.get(source):
            return _imap_clients[source].send_email(to, subject, body, reply_to_id=email_id)
    except Exception as e:
        print(f"[!] Error sending reply: {e}")
    return False
