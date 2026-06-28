"""LLM-evaluation harness for the ECNL MCP server.

The harness replays a small set of reference scenarios — each a tool
sequence with expected output keywords — against the MCP server's
tool surface. It serves two purposes:

* **Drift detection.** A nightly job (see `.github/workflows/evals.yml`)
  replays the scenarios against the deployed Fly instance and reports
  per-tool pass/fail. A drop in pass rate flags a regression in either
  the upstream API shape or the formatter layer.
* **Documentation.** Every scenario file under :mod:`tests.evals.scenarios`
  doubles as a worked example of how to call the tool — readable by
  humans and by AI assistants exploring the codebase.

The harness intentionally does not require an LLM by default. A
follow-up phase will swap the ``expected_contains`` heuristic for an
LLM-as-judge that scores the response semantically — until then the
golden-keyword check is a pragmatic stand-in.
"""

from .runner import ScenarioResult, run_scenario
from .scenario_loader import Scenario, load_scenarios

__all__ = ["Scenario", "ScenarioResult", "load_scenarios", "run_scenario"]
