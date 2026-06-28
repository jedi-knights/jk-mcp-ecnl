"""JWKS client for fetching auth-server's signing keys.

Per identity-platform-go ADR-0008, the auth-server publishes its RSA
public keys at ``/.well-known/jwks.json``. This module wraps that
endpoint with a small caching layer keyed on ``kid`` (RFC 7517 §4.5)
so a token whose JOSE header references a known key validates without
a network round-trip on every request.

The cache TTL is intentionally long (default 1 hour). A key rotation
takes effect on the next refresh — auth-server's rotation cadence
(ADR-0008) is operator-controlled at a scale of days, so a one-hour
staleness window is harmless. A token signed with a not-yet-cached
key triggers an immediate refetch so newly-promoted keys validate
without waiting for the TTL.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx
import jwt
from jwt import PyJWK

logger = logging.getLogger(__name__)


@dataclass
class JWKSCache:
    """In-memory cache of JWKS entries keyed by ``kid``.

    The cache is intentionally per-process — every MCP server replica
    fetches its own copy. Sharing across replicas via Redis would add
    operational complexity for negligible gain at the volumes the MCP
    deployment sees today.
    """

    issuer_url: str
    ttl_seconds: int = 3600
    http_client: httpx.AsyncClient | None = None

    _keys: dict[str, PyJWK] = field(default_factory=dict, init=False)
    _expires_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def get(self, kid: str) -> PyJWK:
        """Return the JWK for ``kid``.

        Triggers a refresh when the cache is stale or the requested
        ``kid`` is unknown. Raises :class:`KeyError` when the kid is
        still missing after a fresh fetch — auth-server has rotated
        beyond this key or the caller is using a forged header.
        """
        async with self._lock:
            if self._stale() or kid not in self._keys:
                await self._refresh()
            try:
                return self._keys[kid]
            except KeyError as exc:
                raise KeyError(f"unknown JWKS kid: {kid}") from exc

    def _stale(self) -> bool:
        return time.time() >= self._expires_at

    async def _refresh(self) -> None:
        client = self.http_client or httpx.AsyncClient(timeout=5.0)
        owns_client = self.http_client is None
        url = self.issuer_url.rstrip("/") + "/.well-known/jwks.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        finally:
            if owns_client:
                await client.aclose()

        keys: dict[str, PyJWK] = {}
        for raw in payload.get("keys", []):
            try:
                kid = raw["kid"]
            except KeyError:
                logger.warning("JWKS entry missing kid; skipping: %s", raw)
                continue
            keys[kid] = PyJWK(raw)
        self._keys = keys
        self._expires_at = time.time() + self.ttl_seconds
        logger.debug("JWKS cache refreshed: %d keys, ttl=%ds", len(keys), self.ttl_seconds)


def jwks_url(issuer_url: str) -> str:
    """Compose the well-known JWKS URL from an issuer base.

    Public so server-side wiring code can log the resolved URL at
    startup without re-deriving it; the join logic is trivial but
    centralizing it keeps the contract with auth-server in one spot.
    """
    return issuer_url.rstrip("/") + "/.well-known/jwks.json"


# Tiny PyJWT alias re-exported so test fixtures can construct fake
# tokens without importing PyJWT directly — keeps the test surface
# coupled to this module rather than the underlying library.
encode = jwt.encode
