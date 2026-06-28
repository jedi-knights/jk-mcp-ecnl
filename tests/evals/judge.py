"""LLM-as-judge backend for semantic scenario assertions.

The substring-based ``expected_contains`` check covers deterministic
output well — stub-mode replays produce identical strings every run,
so an exact-match assertion is the cheapest reliable signal. It
breaks down for outputs whose *phrasing* varies but whose *meaning*
should be preserved: live-mode replays against real upstreams, or
formatter refactors that legitimately reshape whitespace + ordering
without changing the information conveyed.

``expected_judge`` is the escape hatch. Each criterion in the list is
graded by Claude against the joined tool output, returning a strict
PASS / FAIL plus a one-line rationale (so failures are debuggable
without re-running). The judge is opt-in twice: the scenario must
declare ``expected_judge``, and the test process must export
``ANTHROPIC_API_KEY``. Without the key the judge tests skip cleanly
so contributor PR runs without a key remain green.

Default model is :data:`DEFAULT_MODEL` — Haiku is more than capable
of a yes/no grading task on a few hundred tokens of soccer-data
output, and the cost difference relative to Sonnet/Opus matters when
this runs nightly across N servers × M scenarios × K criteria.
Operators who want a different model set ``MCP_EVAL_JUDGE_MODEL``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
"""Latest Haiku at the time the harness shipped. Sized for short
PASS/FAIL grading; operators override via ``MCP_EVAL_JUDGE_MODEL``."""

_VERDICT_RE = re.compile(r"^\s*VERDICT\s*:\s*(PASS|FAIL)\b", re.IGNORECASE | re.MULTILINE)
_REASON_RE = re.compile(r"^\s*REASON\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

_SYSTEM_PROMPT = (
    "You are grading a single criterion against tool output from an MCP server. "
    "Your only job is to decide whether the criterion is satisfied by the output. "
    "Be strict: if the criterion is not clearly satisfied, return FAIL. "
    "Respond on exactly two lines, no preamble, no markdown:\n"
    "VERDICT: PASS or FAIL\n"
    "REASON: one short sentence"
)


@dataclass(frozen=True)
class JudgeVerdict:
    """A single PASS/FAIL grading from the judge.

    ``reason`` is surfaced in the assertion message on failure so the
    cause is visible in the pytest report — no need to re-run the
    judge to understand why a criterion failed.
    """

    passed: bool
    reason: str


class Judge(Protocol):
    """Grading port. Pluggable so tests can inject a stub judge
    without spending real tokens."""

    async def evaluate(self, criterion: str, output: str) -> JudgeVerdict:
        """Grade ``output`` against ``criterion``."""
        ...


class ClaudeJudge:
    """Claude-backed judge using the anthropic SDK.

    Constructed once per test process (lazily, on first judge use) so
    the HTTP client is reused across criteria. Each ``evaluate`` call
    is a single round trip; we do not batch because criteria are
    independent and parallelism gains aren't worth the failure-mode
    complexity for nightly cadence.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        # Import lazily so the module imports cleanly when the SDK is
        # missing in environments that never enable the judge.
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def evaluate(self, criterion: str, output: str) -> JudgeVerdict:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=128,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Criterion: {criterion}\n\nTool output:\n{output}",
                }
            ],
        )
        text_parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
        return parse_verdict("\n".join(text_parts))


def parse_verdict(response: str) -> JudgeVerdict:
    """Parse the model's two-line response into a :class:`JudgeVerdict`.

    Tolerates surrounding whitespace, case variations, and missing
    REASON lines (treated as an empty rationale). A response without
    a parseable VERDICT line is treated as FAIL with the raw text as
    the reason — defensive default so a malformed grading never
    silently passes.
    """
    verdict_match = _VERDICT_RE.search(response)
    reason_match = _REASON_RE.search(response)
    reason = reason_match.group(1).strip() if reason_match else ""
    if verdict_match is None:
        return JudgeVerdict(passed=False, reason=f"unparseable judge response: {response!r}")
    return JudgeVerdict(passed=verdict_match.group(1).upper() == "PASS", reason=reason)


def judge_from_env() -> ClaudeJudge | None:
    """Construct a :class:`ClaudeJudge` from environment variables.

    Returns ``None`` when ``ANTHROPIC_API_KEY`` is missing so callers
    can use the presence/absence as a skip signal without parsing
    env vars themselves.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("MCP_EVAL_JUDGE_MODEL") or DEFAULT_MODEL
    return ClaudeJudge(api_key=api_key, model=model)
