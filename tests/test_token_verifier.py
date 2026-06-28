"""Tests for the JWKS-backed token verifier.

The verifier sits at the trust boundary between an upstream caller
(typically auth-server via the MCP gateway) and the NWSL tool surface.
The tests focus on the failure shape rather than the happy path: any
rejected token must return ``None`` and never raise, every claim
required by ADR-0008 / ADR-0010 must be enforced, and the JWKS cache
must refetch when a fresh ``kid`` appears.

The fixtures generate a real RSA keypair so the verifier is exercised
end-to-end against PyJWT's RS256 backend rather than a mock signature.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK

from ecnl.security.jwks import JWKSCache, jwks_url
from ecnl.security.token_verifier import (
    JWKSTokenVerifier,
    _env_flag,
    _env_int,
    build_token_verifier,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset every MCP_AUTH_* env var the verifier reads."""
    for name in [
        "MCP_AUTH_ENABLED",
        "MCP_AUTH_ISSUER_URL",
        "MCP_AUTH_RESOURCE_URL",
        "MCP_AUTH_JWKS_TTL_SECONDS",
        "MCP_AUTH_LEEWAY_SECONDS",
    ]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def rsa_keypair():
    """Yield a fresh RSA keypair for each test.

    Fresh per-test means a leaked key is never reused; key generation
    is cheap enough at 2048 bits that the suite stays under a few
    seconds even with one key per test.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _jwk_from_public_pem(public_pem: bytes, kid: str) -> PyJWK:
    """Convert a PEM public key into the JWK shape JWKSCache stores."""
    return PyJWK.from_json(_jwk_json_from_pem(public_pem, kid))


def _jwk_json_from_pem(public_pem: bytes, kid: str) -> str:
    """Render a PEM public key as the JSON wire shape JWKS publishes."""
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

    pub: RSAPublicKey = serialization.load_pem_public_key(public_pem)
    n = pub.public_numbers().n
    e = pub.public_numbers().e
    import base64
    import json

    def b64url(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return json.dumps({"kty": "RSA", "kid": kid, "alg": "RS256", "n": b64url(n), "e": b64url(e), "use": "sig"})


def _verifier_with_jwks(private_pem: bytes, public_pem: bytes, *, kid: str = "k1",
                       issuer: str = "https://auth.test",
                       audience: str | None = "https://mcp.test") -> tuple[JWKSTokenVerifier, JWKSCache]:
    cache = JWKSCache(issuer_url=issuer)
    cache._keys = {kid: _jwk_from_public_pem(public_pem, kid)}
    cache._expires_at = time.time() + 3600
    return JWKSTokenVerifier(issuer=issuer, audience=audience, jwks=cache), cache


def _make_token(private_pem: bytes, *, kid: str = "k1", claims_override: dict[str, Any] | None = None) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "https://auth.test",
        "sub": "user-omar",
        "aud": "https://mcp.test",
        "exp": now + 300,
        "iat": now,
        "client_id": "client-A",
        "scope": "read write",
        "actor_type": "agent",
        "agent_id": "agent-claude",
    }
    if claims_override:
        claims.update(claims_override)
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# verify_token — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_token_accepts_valid_rs256(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    token = _make_token(private_pem)

    result = await verifier.verify_token(token)

    assert result is not None
    assert result.client_id == "client-A"
    assert "read" in result.scopes and "write" in result.scopes


@pytest.mark.asyncio
async def test_verify_token_surfaces_actor_type_and_agent_id(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    token = _make_token(private_pem)

    result = await verifier.verify_token(token)

    assert result is not None
    assert "actor_type:agent" in result.scopes
    assert "agent_id:agent-claude" in result.scopes
    assert "sub:user-omar" in result.scopes


# ---------------------------------------------------------------------------
# verify_token — rejection paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_token_rejects_malformed(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    assert await verifier.verify_token("not-a-jwt") is None


@pytest.mark.asyncio
async def test_verify_token_rejects_missing_kid(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    # Build a token whose header has no kid by signing directly.
    now = int(time.time())
    token = jwt.encode(
        {"iss": "https://auth.test", "sub": "u", "aud": "https://mcp.test", "exp": now + 60, "iat": now},
        private_pem,
        algorithm="RS256",
    )
    assert await verifier.verify_token(token) is None


@pytest.mark.asyncio
async def test_verify_token_rejects_unknown_kid(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    token = _make_token(private_pem, kid="not-in-cache")
    # The cache will attempt to refresh; stub it out to raise so the
    # verifier sees the kid as unknown.
    verifier.jwks._refresh = AsyncMock()
    assert await verifier.verify_token(token) is None


@pytest.mark.asyncio
async def test_verify_token_rejects_wrong_issuer(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    token = _make_token(private_pem, claims_override={"iss": "https://attacker.example"})
    assert await verifier.verify_token(token) is None


@pytest.mark.asyncio
async def test_verify_token_rejects_wrong_audience(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    token = _make_token(private_pem, claims_override={"aud": "https://other.mcp"})
    assert await verifier.verify_token(token) is None


@pytest.mark.asyncio
async def test_verify_token_rejects_expired(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    token = _make_token(private_pem, claims_override={"exp": int(time.time()) - 600})
    assert await verifier.verify_token(token) is None


@pytest.mark.asyncio
async def test_verify_token_rejects_missing_required_claim(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    # Subject is required; PyJWT decodes successfully but raises
    # MissingRequiredClaimError when sub is absent.
    now = int(time.time())
    token = jwt.encode(
        {"iss": "https://auth.test", "aud": "https://mcp.test", "exp": now + 60, "iat": now},
        private_pem,
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    assert await verifier.verify_token(token) is None


@pytest.mark.asyncio
async def test_verify_token_rejects_bad_signature(rsa_keypair) -> None:
    private_pem, public_pem = rsa_keypair
    verifier, _ = _verifier_with_jwks(private_pem, public_pem)
    # Sign with a different keypair.
    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rogue_pem = rogue_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = _make_token(rogue_pem)
    assert await verifier.verify_token(token) is None


# ---------------------------------------------------------------------------
# build_token_verifier — env-driven construction
# ---------------------------------------------------------------------------


def test_build_token_verifier_returns_none_when_disabled() -> None:
    assert build_token_verifier() is None


def test_build_token_verifier_returns_none_when_explicitly_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ENABLED", "false")
    assert build_token_verifier() is None


def test_build_token_verifier_raises_when_enabled_without_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ENABLED", "true")
    with pytest.raises(RuntimeError, match="MCP_AUTH_ISSUER_URL"):
        build_token_verifier()


def test_build_token_verifier_constructs_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ENABLED", "true")
    monkeypatch.setenv("MCP_AUTH_ISSUER_URL", "https://auth.test")
    monkeypatch.setenv("MCP_AUTH_RESOURCE_URL", "https://mcp.test")

    v = build_token_verifier()

    assert v is not None
    assert v.issuer == "https://auth.test"
    assert v.audience == "https://mcp.test"


def test_build_token_verifier_audience_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ENABLED", "true")
    monkeypatch.setenv("MCP_AUTH_ISSUER_URL", "https://auth.test")
    v = build_token_verifier()
    assert v is not None
    assert v.audience is None


def test_build_token_verifier_honors_ttl_and_leeway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ENABLED", "true")
    monkeypatch.setenv("MCP_AUTH_ISSUER_URL", "https://auth.test")
    monkeypatch.setenv("MCP_AUTH_JWKS_TTL_SECONDS", "120")
    monkeypatch.setenv("MCP_AUTH_LEEWAY_SECONDS", "5")
    v = build_token_verifier()
    assert v is not None
    assert v.jwks.ttl_seconds == 120
    assert v.leeway_seconds == 5


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwks_cache_fetches_on_miss(rsa_keypair) -> None:
    _, public_pem = rsa_keypair
    cache = JWKSCache(issuer_url="https://auth.test")
    payload = {"keys": [_jwk_dict(public_pem, "k1")]}

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_FakeResp(payload))):
        key = await cache.get("k1")
    assert key is not None


@pytest.mark.asyncio
async def test_jwks_cache_refreshes_when_kid_unknown(rsa_keypair) -> None:
    _, public_pem = rsa_keypair
    cache = JWKSCache(issuer_url="https://auth.test")
    cache._keys = {"k1": _jwk_from_public_pem(public_pem, "k1")}
    cache._expires_at = time.time() + 3600  # not stale

    payload = {"keys": [_jwk_dict(public_pem, "k1"), _jwk_dict(public_pem, "k2")]}
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_FakeResp(payload))):
        key = await cache.get("k2")
    assert key is not None


@pytest.mark.asyncio
async def test_jwks_cache_raises_keyerror_for_unknown_kid(rsa_keypair) -> None:
    _, public_pem = rsa_keypair
    cache = JWKSCache(issuer_url="https://auth.test")
    payload = {"keys": [_jwk_dict(public_pem, "k1")]}
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_FakeResp(payload))), pytest.raises(KeyError):
        await cache.get("never-issued")


def test_jwks_url_strips_trailing_slash() -> None:
    assert jwks_url("https://auth.test/") == "https://auth.test/.well-known/jwks.json"
    assert jwks_url("https://auth.test") == "https://auth.test/.well-known/jwks.json"


# ---------------------------------------------------------------------------
# env-flag helpers
# ---------------------------------------------------------------------------


def test_env_flag_handles_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "On"):
        monkeypatch.setenv("FLAG", value)
        assert _env_flag("FLAG") is True


def test_env_flag_handles_falsey_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("", "0", "false", "no", "off", "random"):
        monkeypatch.setenv("FLAG", value)
        assert _env_flag("FLAG") is False


def test_env_int_returns_default_on_bad_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAL", "not-a-number")
    assert _env_int("VAL", 42) == 42


def test_env_int_parses_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAL", "120")
    assert _env_int("VAL", 0) == 120


# ---------------------------------------------------------------------------
# Helpers used inline above
# ---------------------------------------------------------------------------


def _jwk_dict(public_pem: bytes, kid: str) -> dict[str, str]:
    import json as _json

    return _json.loads(_jwk_json_from_pem(public_pem, kid))


class _FakeResp:
    """Minimal stand-in for the slice of httpx.Response the JWKS cache uses."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload
