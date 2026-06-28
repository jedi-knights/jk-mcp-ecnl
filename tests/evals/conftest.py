"""pytest fixtures for the eval harness.

Provides ``mcp_client`` — an async ``ClientSession`` connected to an
in-process FastMCP instance whose outbound AthleteOne adapter is a
stub returning deterministic domain objects. Scenarios run hermetically
in unit-test CI without contacting the live AthleteOne API.

The nightly drift run (see ``.github/workflows/evals.yml``) overrides
this fixture with a transport pointed at the deployed Fly instance so
the same scenarios exercise the live wire shape without any change to
the runner.

The stubs cover only the small slice of upstream calls the registered
scenarios exercise. Adding a scenario that calls a new tool means
adding the matching stub method here — there is no automatic
discovery. The trade-off is deliberate: scenarios act as both
documentation and contract tests, so explicitly listing the supported
shape keeps the test surface honest.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecnl.domain.models import Club, Event


@dataclass
class _StubRepo:
    """Application-port stub returning deterministic domain objects.

    Only the methods the registered scenarios call are implemented.
    Adding a scenario that hits an unimplemented tool will surface an
    AttributeError — the explicit failure mode is the right one for
    a contract-test harness.
    """

    async def get_clubs(self, event_id: int) -> list[Club]:
        _ = event_id
        return [
            Club(club_id=4242, name="Sample SC", city="Boston", state_code="MA"),
        ]


@dataclass
class _StubDiscovery:
    """Discovery-port stub matching the same minimal-scope rule as the
    repo stub above. ``find_events`` is the only discovery method any
    registered scenario reaches; anything else surfaces a clean
    NotImplementedError via the catch-all ``__getattr__``."""

    async def find_events(
        self,
        league: str | None = None,
        gender: str | None = None,
        season: str | None = None,
    ) -> list[Event]:
        _ = (league, gender, season)
        return [_north_atlantic_event()]

    def __getattr__(self, name: str):
        raise NotImplementedError(f"eval harness: discovery port not wired for {name!r}")


def _north_atlantic_event() -> Event:
    return Event(
        event_id=3933,
        name="ECNL Girls North Atlantic 2025-26",
        league="ECNL",
        gender="girls",
        conference="North Atlantic",
        season="2025-26",
    )


class _NotWired:
    """Sentinel that raises on any attribute access.

    Used in place of out-of-scope dependencies so an accidental tool
    call against an un-stubbed surface produces an obvious error
    rather than a confusing one downstream.
    """

    def __getattr__(self, name: str):
        raise NotImplementedError(f"eval harness: dependency port not wired for {name!r}")
