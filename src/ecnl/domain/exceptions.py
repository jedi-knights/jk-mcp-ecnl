"""Domain exceptions for the ECNL application.

All exceptions raised by the application layer or adapters are rooted here.
Callers can catch ECNLError to handle any domain-level failure, or catch
subclasses for finer-grained handling.
"""


class ECNLError(Exception):
    """Base class for all ECNL domain exceptions."""


class ECNLNotFoundError(ECNLError):
    """Raised when the requested resource does not exist (HTTP 404 or empty result)."""


class UpstreamAPIError(ECNLError):
    """Raised when the upstream AthleteOne API returns an unexpected error.

    Covers non-2xx HTTP responses and ``{"result": "error"}`` envelopes returned
    with a 200 status.
    """
