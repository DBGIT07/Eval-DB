from __future__ import annotations

import hashlib
import secrets


def generate_api_key() -> str:
    return f"sk_proj_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str, hash: str) -> bool:
    return hash_api_key(key) == hash
