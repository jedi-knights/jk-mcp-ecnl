"""Scenario loader — parses YAML files under ``tests/evals/scenarios/``.

A scenario file is a small YAML document describing one prompt-to-tools
walkthrough. The format is deliberately flat so a contributor adding a
scenario does not need to read this module to follow the existing ones.

Example::

    name: get_current_standings
    description: User asks for the current NWSL standings
    tool_sequence:
      - tool: get_standings
        args: {}
    expected_contains:
      - "Standings"
      - "GP"

The loader resolves paths relative to ``tests/evals/scenarios/`` so the
test discovery does not depend on the caller's CWD.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ToolCall:
    """One tool dispatch inside a scenario.

    ``args`` defaults to an empty dict so the scenario YAML can omit it
    for parameter-free tools (``get_teams``, ``get_standings``).
    """

    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    """A single eval scenario.

    Field semantics:

    * ``name`` — file-system-safe identifier; used as the report key.
    * ``description`` — human-readable prompt (an LLM judge would read
      this to score the response in a future phase).
    * ``tool_sequence`` — the tools the scenario invokes, in order.
    * ``expected_contains`` — strings that must appear in the joined
      tool outputs for the scenario to pass. Treated as a substring
      check — case-insensitive on Windows-style line endings would be
      brittle, so the match is exact.
    """

    name: str
    description: str
    tool_sequence: list[ToolCall]
    expected_contains: list[str]


_SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def load_scenarios(directory: Path | None = None) -> list[Scenario]:
    """Read every ``*.yaml`` file under ``directory`` as a Scenario.

    ``directory`` defaults to ``tests/evals/scenarios/`` so the call
    site stays free of path plumbing. Scenarios are returned sorted by
    name so the report ordering is stable.
    """
    base = directory or _SCENARIOS_DIR
    out: list[Scenario] = []
    for path in sorted(base.glob("*.yaml")):
        out.append(_parse_scenario(path))
    return out


def _parse_scenario(path: Path) -> Scenario:
    """Read one scenario YAML file into a :class:`Scenario`.

    Validates the required keys (name, description, tool_sequence,
    expected_contains) at parse time so a malformed scenario surfaces
    immediately rather than as an obscure attribute error during
    replay.
    """
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: scenario must be a mapping")
    for key in ("name", "description", "tool_sequence", "expected_contains"):
        if key not in raw:
            raise ValueError(f"{path}: missing required key {key!r}")
    tools = [ToolCall(tool=str(entry["tool"]), args=dict(entry.get("args") or {})) for entry in raw["tool_sequence"]]
    return Scenario(
        name=str(raw["name"]),
        description=str(raw["description"]),
        tool_sequence=tools,
        expected_contains=[str(s) for s in raw["expected_contains"]],
    )
