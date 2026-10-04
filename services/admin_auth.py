from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 310_000
SALT_BYTES = 16


def validate_password(password: str) -> tuple[bool, str]:
    if not password:
        return False, "empty"
    if len(password) < 8:
        return False, "too_short"
    if len(password) > 128:
        return False, "too_long"
    return True, ""


def hash_password(password: str) -> str:
    ok, reason = validate_password(password)
    if not ok:
        raise ValueError(reason)
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        iterations_i = int(iterations)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations_i)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
