"""TokenVerifier implementation for the streamable-http transport.

Implements ``mcp.server.auth.provider.TokenVerifier`` against the
auth-server's JWKS endpoint. Validates RS256-signed access tokens per
identity-platform-go ADR-0008 / ADR-0010 / ADR-0015 — the token's
``iss`` must match the configured issuer, the signing key must be the
one auth-server's JWKS publishes for the JOSE header's ``kid``, the
token must not be expired, and (when configured) the ``aud`` claim
must include the resource server's URL.

The verifier surfaces ``actor_type`` and ``agent_id`` claims (ADR-0015)
through ``AccessToken.scopes`` and an extra dict so downstream
authorization decisions can read the principal kind without re-parsing
the JWT.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import jwt
from mcp.server.auth.provider import AccessToken

from .jwks import JWKSCache

logger = logging.getLogger(__name__)


@dataclass
class JWKSTokenVerifier:
    """RS256 + JWKS bearer-token verifier.

    Implements the duck-typed TokenVerifier protocol the mcp SDK
    expects. Returns ``None`` on every failure — the SDK turns ``None``
    into a 401 response. Avoid leaking the rejection reason in the
    return value; per RFC 6749 §5.2 we never give a client more
    information than ``invalid_token``.
    """

    issuer: str
    """Expected ``iss`` claim. Tokens with any other issuer are rejected
    outright — this is the trust anchor for the entire validation
    chain."""

    audience: str | None
    """Expected ``aud`` claim. When set, the token must list this value
    in its audience array. RFC 8707 resource indicator semantics: this
    is the MCP server's public URL."""

    jwks: JWKSCache
    """Caches and refreshes auth-server's signing keys."""

    leeway_seconds: int = 30
    """Clock-skew tolerance applied to ``exp`` / ``iat`` / ``nbf``."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate the bearer token and project it into an AccessToken.

        Returns ``None`` on every failure (bad signature, expired,
        wrong issuer, wrong audience, unknown ``kid``, missing
        required claim, malformed JWT). The mcp SDK's authentication
        middleware maps that to a 401 response with no body.
        """
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            logger.debug("rejecting token: malformed JOSE header (%s)", exc)
            return None

        kid = header.get("kid")
        if not kid:
            logger.debug("rejecting token: JOSE header missing kid")
            return None

        try:
            key = await self.jwks.get(kid)
        except KeyError as exc:
            logger.debug("rejecting token: %s", exc)
            return None

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=self.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.InvalidTokenError as exc:
            logger.debug("rejecting token: %s", exc)
            return None

        return _to_access_token(token, claims)


def _to_access_token(raw: str, claims: dict) -> AccessToken:
    """Project verified claims into the mcp SDK's AccessToken shape.

    ``client_id`` mirrors the JWT's ``client_id`` claim (set by
    auth-server on every issued token); ``scopes`` parses the
    space-delimited RFC 9068 ``scope`` claim. ``actor_type``,
    ``agent_id``, and ``sub`` are duplicated into the scopes list as
    ``actor_type:<value>`` etc. so downstream policy code can read them
    via the SDK without a separate claim accessor. The raw claims are
    not exposed by the AccessToken model — duplicating into scopes is
    the conventional bridge.
    """
    scopes = _parse_scope(claims.get("scope"))
    if actor_type := claims.get("actor_type"):
        scopes.append(f"actor_type:{actor_type}")
    if agent_id := claims.get("agent_id"):
        scopes.append(f"agent_id:{agent_id}")
    if sub := claims.get("sub"):
        scopes.append(f"sub:{sub}")
    return AccessToken(
        token=raw,
        client_id=str(claims.get("client_id") or claims.get("sub") or ""),
        scopes=scopes,
        expires_at=int(claims["exp"]),
    )


def _parse_scope(scope: str | None) -> list[str]:
    """Split a space-delimited RFC 9068 scope claim into a list."""
    if not scope:
        return []
    return [s for s in scope.split() if s]


def build_token_verifier() -> JWKSTokenVerifier | None:
    """Build the verifier from environment variables.

    Returns ``None`` when ``MCP_AUTH_ENABLED`` is unset or false — the
    caller in :mod:`ecnl.server` interprets that as "skip the auth
    middleware entirely" and leaves the streamable-http transport
    open. Defaulting to off keeps the local-dev flow unchanged.

    Required when enabled:
      * ``MCP_AUTH_ISSUER_URL`` — auth-server origin used to discover
        JWKS and validate the ``iss`` claim.

    Optional:
      * ``MCP_AUTH_RESOURCE_URL`` — this server's public URL; when set
        every token must list it in its ``aud`` claim (RFC 8707).
      * ``MCP_AUTH_JWKS_TTL_SECONDS`` — JWKS cache lifetime (default 3600).
      * ``MCP_AUTH_LEEWAY_SECONDS`` — clock-skew tolerance (default 30).
    """
    if not _env_flag("MCP_AUTH_ENABLED"):
        return None
    issuer = os.environ.get("MCP_AUTH_ISSUER_URL", "").strip()
    if not issuer:
        raise RuntimeError("MCP_AUTH_ENABLED is true but MCP_AUTH_ISSUER_URL is unset")
    resource = os.environ.get("MCP_AUTH_RESOURCE_URL", "").strip() or None
    ttl = _env_int("MCP_AUTH_JWKS_TTL_SECONDS", 3600)
    leeway = _env_int("MCP_AUTH_LEEWAY_SECONDS", 30)
    return JWKSTokenVerifier(
        issuer=issuer,
        audience=resource,
        jwks=JWKSCache(issuer_url=issuer, ttl_seconds=ttl),
        leeway_seconds=leeway,
    )


def _env_flag(name: str, default: bool = False) -> bool:
    """Read an env var as a boolean.

    Accepts ``1``, ``true``, ``yes``, ``on`` (case-insensitive) as true.
    """
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Read an env var as an int, returning ``default`` on bad input."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using default %d", name, raw, default)
        return default
