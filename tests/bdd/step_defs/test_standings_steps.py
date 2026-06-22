"""Step definitions for the standings/schedule smoke feature.

When-steps run their async service calls via ``asyncio.run`` because pytest-bdd
drives steps synchronously and does not await coroutine step functions.
"""

import asyncio

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ecnl.application.service import ECNLService
from ecnl.ports.outbound import DiscoveryPort, ECNLAPIPort

scenarios("../features/standings.feature")


@pytest.fixture
def context() -> dict:
    """Mutable bag for passing state between steps."""
    return {}


@given("a stubbed ECNL data source")
def _stub_source(context: dict, mocker, sample_standings, sample_schedule):
    repo = mocker.AsyncMock(spec=ECNLAPIPort)
    repo.get_standings.return_value = sample_standings
    repo.get_schedule.return_value = sample_schedule
    discovery = mocker.AsyncMock(spec=DiscoveryPort)
    context["service"] = ECNLService(repo=repo, discovery=discovery)


@when(parsers.parse("I request the standings for event {event_id:d} flight {flight_id:d}"))
def _request_standings(context: dict, event_id: int, flight_id: int):
    context["standings"] = asyncio.run(context["service"].get_standings(event_id, 18755, flight_id))


@when(parsers.parse("I request the results for event {event_id:d} flight {flight_id:d}"))
def _request_results(context: dict, event_id: int, flight_id: int):
    context["results"] = asyncio.run(context["service"].get_results(event_id, flight_id))


@then(parsers.parse('the standings leader is "{name}"'))
def _assert_leader(context: dict, name: str):
    assert context["standings"].rows[0].team_name == name


@then(parsers.parse("{count:d} completed match is returned"))
def _assert_result_count(context: dict, count: int):
    assert len(context["results"]) == count
