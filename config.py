"""
Configuración del Agente de Correo Electrónico.
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Directorio base del proyecto
BASE_DIR = Path(__file__).parent

# --- Flask ---
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")

# --- Gmail ---
GMAIL_CREDENTIALS_FILE = BASE_DIR / "gmail_credentials.json"
GMAIL_TOKEN_FILE = BASE_DIR / "gmail_token.json"

# En producción, crear gmail_credentials.json desde variable de entorno
_gmail_creds_json = os.getenv("GMAIL_CREDENTIALS_JSON", "").strip().lstrip("=")
if _gmail_creds_json:
    GMAIL_CREDENTIALS_FILE.write_text(_gmail_creds_json)
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
GMAIL_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", "http://127.0.0.1:5000/auth/gmail/callback").strip().lstrip("=")

# --- Outlook / Hotmail ---
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID", "")
OUTLOOK_TENANT_ID = os.getenv("OUTLOOK_TENANT_ID", "consumers")
OUTLOOK_SCOPES = ["Mail.ReadWrite", "Mail.Send"]
OUTLOOK_TOKEN_CACHE = BASE_DIR / "outlook_token_cache.json"
OUTLOOK_AUTHORITY = f"https://login.microsoftonline.com/{OUTLOOK_TENANT_ID}"

# --- IMAP (cuentas genéricas) ---
# JSON string: [{"name":"...", "host":"...", "port":993, "email":"...", "password":"...", "smtp_host":"...", "smtp_port":587}]
_imap_raw = os.getenv("IMAP_ACCOUNTS", "[]")
try:
    IMAP_ACCOUNTS: list[dict] = json.loads(_imap_raw)
except (json.JSONDecodeError, TypeError):
    IMAP_ACCOUNTS = []

# --- OpenAI / ChatGPT ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-4o"

# --- Base de datos ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///email_agent.db")

# --- Cifrado de tokens ---
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")

# --- Google Sign-In (autenticación de usuarios, NO Gmail API) ---
GOOGLE_SIGN_IN_CLIENT_ID = os.getenv("GOOGLE_SIGN_IN_CLIENT_ID", "")
GOOGLE_SIGN_IN_CLIENT_SECRET = os.getenv("GOOGLE_SIGN_IN_CLIENT_SECRET", "")
GOOGLE_SIGN_IN_REDIRECT_URI = os.getenv("GOOGLE_SIGN_IN_REDIRECT_URI", "http://127.0.0.1:5000/auth/google/callback")

# --- General ---
MAX_EMAILS_TO_FETCH = 50
