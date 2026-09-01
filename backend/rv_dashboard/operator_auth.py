from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import deque
from threading import Lock


SCHEME = "pbkdf2_sha256"
ITERATIONS = 240_000


def validate_operator_pin(pin: str) -> str:
    if not pin.isascii() or not pin.isdigit() or not 4 <= len(pin) <= 12:
        raise ValueError("Operator PIN must contain 4 through 12 digits")
    return pin


def hash_operator_pin(pin: str) -> str:
    validated = validate_operator_pin(pin)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", validated.encode(), salt, ITERATIONS)
    return "$".join(
        (
            SCHEME,
            str(ITERATIONS),
            base64.urlsafe_b64encode(salt).decode().rstrip("="),
            base64.urlsafe_b64encode(digest).decode().rstrip("="),
        )
    )


def verify_operator_pin(pin: str, encoded: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if scheme != SCHEME:
            return False
        iterations = int(iterations_raw)
        if not 100_000 <= iterations <= 1_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_raw + "=" * (-len(salt_raw) % 4))
        expected = base64.urlsafe_b64decode(digest_raw + "=" * (-len(digest_raw) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


class OperatorPinGuard:
    """Small process-local brute-force guard for the trusted-LAN control."""

    def __init__(self, maximum_failures: int = 5, window_seconds: int = 300) -> None:
        self.maximum_failures = maximum_failures
        self.window_seconds = window_seconds
        self._failures: deque[float] = deque()
        self._lock = Lock()

    def check(self, pin: str, encoded: str, *, now: float | None = None) -> str:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            cutoff = timestamp - self.window_seconds
            while self._failures and self._failures[0] <= cutoff:
                self._failures.popleft()
            if len(self._failures) >= self.maximum_failures:
                return "locked"
            if not verify_operator_pin(pin, encoded):
                self._failures.append(timestamp)
                return "denied"
            self._failures.clear()
            return "allowed"
