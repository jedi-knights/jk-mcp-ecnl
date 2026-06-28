"""Scenario runner — replays a scenario against an MCP client session.

The runner is transport-agnostic: it accepts a connected
``mcp.client.session.ClientSession`` and dispatches each tool call via
the public ``call_tool`` API. In CI we connect over an in-process
stdio bridge (see :mod:`tests.evals.conftest`) so the eval suite has
no network dependency on the deployed Fly instance. The nightly
GitHub Action overrides the fixture to connect to the live URL.

A scenario passes when every ``expected_contains`` string is present
in the joined text outputs of the tool sequence. Failures are
returned (not raised) so the runner can produce a report covering
every scenario in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp.client.session import ClientSession

from .scenario_loader import Scenario


@dataclass
class ScenarioResult:
    """Outcome of replaying one scenario.

    ``passed`` is True only when every ``expected_contains`` string was
    present in at least one tool's text output. ``missing`` lists the
    expected strings that were not found — empty on success. ``errors``
    captures per-step exceptions so a tool call that raised does not
    mask the rest of the sequence.
    """

    name: str
    passed: bool
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output: str = ""


async def run_scenario(scenario: Scenario, client: ClientSession) -> ScenarioResult:
    """Execute every tool in the scenario and check the expectations.

    Each tool's text content is concatenated with newlines and the
    expected substrings are checked against the joined output. The
    result object captures both the missing substrings and any per-step
    errors so a single failing tool does not hide a later mismatch.
    """
    outputs: list[str] = []
    errors: list[str] = []
    for step in scenario.tool_sequence:
        try:
            response = await client.call_tool(step.tool, arguments=step.args)
        except Exception as exc:
            errors.append(f"{step.tool}: {exc!r}")
            continue
        outputs.append(_extract_text(response))

    joined = "\n".join(outputs)
    missing = [s for s in scenario.expected_contains if s not in joined]
    return ScenarioResult(
        name=scenario.name,
        passed=not missing and not errors,
        missing=missing,
        errors=errors,
        output=joined,
    )


def _extract_text(response: Any) -> str:
    """Flatten the ``CallToolResult.content`` list into a plain string.

    The mcp SDK returns a list of typed content blocks (text, image,
    embedded resource). The eval harness only inspects text blocks; the
    other types are stringified via ``str()`` so a scenario that
    accidentally calls a tool returning binary content gets a readable
    error rather than a crash.
    """
    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            text_parts.append(str(text))
        else:
            text_parts.append(str(block))
    return "\n".join(text_parts)
