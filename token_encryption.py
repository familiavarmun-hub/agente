"""
Cifrado y descifrado de credenciales con Fernet.
"""
import json

from cryptography.fernet import Fernet

import config


def _get_fernet() -> Fernet:
    return Fernet(config.TOKEN_ENCRYPTION_KEY.encode())


def encrypt_token(data: dict) -> str:
    """Cifra un dict de credenciales y devuelve string base64."""
    raw = json.dumps(data).encode()
    return _get_fernet().encrypt(raw).decode()


def decrypt_token(encrypted: str) -> dict:
    """Descifra string base64 y devuelve dict de credenciales."""
    raw = _get_fernet().decrypt(encrypted.encode())
    return json.loads(raw.decode())
