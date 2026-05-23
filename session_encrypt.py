import base64
import os
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _derive_key(secret: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000)
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def make_key_from_secret(secret: str) -> Optional[bytes]:
    if not secret:
        return None
    salt = b"leadops_session_v1"
    return _derive_key(secret, salt)


def encrypt_state(state: Dict[str, Any], key: bytes) -> str:
    import json
    f = Fernet(key)
    data = json.dumps(state).encode()
    return f.encrypt(data).decode()


def decrypt_state(token: str, key: bytes) -> Optional[Dict[str, Any]]:
    import json
    try:
        f = Fernet(key)
        data = f.decrypt(token.encode())
        return json.loads(data)
    except Exception:
        return None
