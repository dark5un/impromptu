"""Phone-remote pairing tokens.

`impromptu pair` used to print a token and a `/remote?token=...` URL, but the
token was generated in the CLI process, never stored, and no route consumed it
-- the advertised URL 404'd.  This module is the shared store the CLI and the
server both talk to.

Tokens are deliberately in-memory and short-lived: pairing authorises a phone
on the local network for one recording session, so surviving a restart is not a
feature.  Nothing is persisted to disk, so no secret outlives the process.
"""
from __future__ import annotations

import secrets
import time
from collections.abc import Callable

DEFAULT_TTL_SECONDS = 600


class PairingStore:
    """In-memory store of unexpired pairing tokens.

    *clock* is injectable so expiry is tested deterministically rather than by
    sleeping.
    """

    def __init__(self, *, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = int(ttl_seconds)
        self._clock = clock
        self._issued: dict[str, float] = {}

    def __len__(self) -> int:
        return len(self._issued)

    def _purge(self, now: float) -> None:
        expired = [token for token, born in self._issued.items() if now - born > self._ttl]
        for token in expired:
            del self._issued[token]

    def issue(self) -> str:
        """Mint a new token, dropping any that have already expired."""
        now = self._clock()
        self._purge(now)
        token = secrets.token_urlsafe(18)
        self._issued[token] = now
        return token

    def validate(self, token: str | None) -> bool:
        """Return whether *token* is known and still inside its TTL."""
        if not token:
            return False
        now = self._clock()
        born = self._issued.get(token)
        if born is None:
            return False
        if now - born > self._ttl:
            del self._issued[token]
            return False
        return True

    def revoke(self, token: str) -> None:
        self._issued.pop(token, None)


__all__ = ["DEFAULT_TTL_SECONDS", "PairingStore"]
