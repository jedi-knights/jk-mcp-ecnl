"""Inbound authorization adapters.

Two implementations:

* :class:`PassThroughAuthorizer` — the default; allows every call.
  This matches the local-dev / stdio posture where the trust boundary
  is the process boundary itself.
* :class:`PolicyServiceAuthorizer` — the production adapter; calls
  ``authorization-policy-service`` per the architecture roadmap.

The factory :func:`build_authorizer` reads the environment and chooses
between them so the composition root (:mod:`nwsl.server`) doesn't have
to branch on config.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from ...ports.inbound import AuthorizationRequest, Authorizer, Decision

logger = logging.getLogger(__name__)


class PassThroughAuthorizer:
    """Authorizer that allows every call.

    Default wiring for local development and the stdio transport.
    Logs each decision at debug so an operator who flips the log
    level can confirm the pass-through is in fact intentional.
    """

    async def authorize(self, req: AuthorizationRequest) -> Decision:
        logger.debug("pass-through authorize: tool=%s actor=%s", req.tool_name, req.actor_type)
        return Decision.allow()


@dataclass
class PolicyServiceAuthorizer:
    """Authorizer backed by ``authorization-policy-service``.

    Maps the MCP tool call onto the policy service's ``/evaluate``
    request shape (``subject_id``, ``resource``, ``action``). The
    resource is ``mcp:<server>:<tool_name>`` so policies can target
    individual tools; the action is ``invoke``.
    """

    base_url: str
    """Public URL of authorization-policy-service. Trailing slashes
    are trimmed at construction time."""

    server_name: str
    """The MCP server's identifier, used as the middle segment of the
    resource path. ``jk-mcp-ecnl`` here; ``jk-mcp-nwsl`` in that repo."""

    http_client: httpx.AsyncClient | None = None
    """Optional pre-built async client. When ``None`` the adapter
    constructs a short-lived client per request. Production wiring
    should pass a shared client so connection pooling kicks in."""

    timeout_seconds: float = 1.5
    """Hard ceiling on policy-evaluation latency. The policy service
    is an in-network call; anything slower than this is a sign that
    the service is unavailable, and per ADR-0019 we fail closed
    rather than hold up the tool dispatch."""

    fail_closed: bool = True
    """When ``True`` (default) any error from the policy call results
    in :meth:`Decision.deny`. Set to ``False`` only in environments
    where availability outranks correctness (typically internal
    staging where a missing policy is a bug, not a security event)."""

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    async def authorize(self, req: AuthorizationRequest) -> Decision:
        body, err = await self._fetch_decision(req)
        if err is not None:
            return self._error_decision(err)
        if bool(body.get("allowed")):
            return Decision.allow()
        # The policy service's reason is acceptable to surface — it
        # already obeys the no-enumeration rule per ADR-0006.
        return Decision.deny(str(body.get("reason") or "tool call not permitted"))

    async def _fetch_decision(self, req: AuthorizationRequest) -> tuple[dict, httpx.HTTPError | None]:
        """POST the authorization request to the policy service.

        Returns ``(body, None)`` on success or ``({}, error)`` when the
        call fails. Split from :meth:`authorize` so each function
        stays under the project's cyclomatic-complexity cap.
        """
        client = self.http_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        owns_client = self.http_client is None
        payload = {
            "subject_id": req.subject or req.client_id or req.agent_id,
            "resource": f"mcp:{self.server_name}:{req.tool_name}",
            "action": "invoke",
        }
        try:
            resp = await client.post(f"{self.base_url}/evaluate", json=payload)
            resp.raise_for_status()
            return resp.json(), None
        except httpx.HTTPError as exc:
            logger.warning("policy service call failed: %s", exc)
            return {}, exc
        finally:
            if owns_client:
                await client.aclose()

    def _error_decision(self, _err: httpx.HTTPError) -> Decision:
        """Decide between deny / allow on a policy-service error.

        ``fail_closed`` is the production default; the staging-only
        flag flips it to allow so a degraded policy service does not
        take down a non-billable environment.
        """
        if self.fail_closed:
            return Decision.deny("authorization unavailable")
        return Decision.allow()


def build_authorizer() -> Authorizer:
    """Construct the authorizer from environment variables.

    Returns :class:`PassThroughAuthorizer` unless
    ``MCP_AUTHZ_URL`` is set to a non-empty value; the presence of the
    URL is what signals that policy enforcement is desired. Other
    knobs:

    * ``MCP_AUTHZ_SERVER_NAME`` — overrides the default server name
      used as the middle segment of the resource path. Defaults to
      ``jk-mcp-ecnl``.
    * ``MCP_AUTHZ_TIMEOUT_SECONDS`` — policy-call ceiling
      (default 1.5).
    * ``MCP_AUTHZ_FAIL_OPEN`` — when truthy, the adapter degrades to
      allow on policy-service errors. Default fail-closed.
    """
    url = os.environ.get("MCP_AUTHZ_URL", "").strip()
    if not url:
        return PassThroughAuthorizer()
    server_name = os.environ.get("MCP_AUTHZ_SERVER_NAME", "jk-mcp-ecnl").strip() or "jk-mcp-ecnl"
    timeout_raw = os.environ.get("MCP_AUTHZ_TIMEOUT_SECONDS", "1.5").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError:
        logger.warning("MCP_AUTHZ_TIMEOUT_SECONDS=%r is not a float; using 1.5", timeout_raw)
        timeout = 1.5
    fail_open = _env_flag("MCP_AUTHZ_FAIL_OPEN")
    return PolicyServiceAuthorizer(
        base_url=url,
        server_name=server_name,
        timeout_seconds=timeout,
        fail_closed=not fail_open,
    )


def _env_flag(name: str, default: bool = False) -> bool:
    """Boolean env-var parser shared with :mod:`nwsl.security`."""
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}
