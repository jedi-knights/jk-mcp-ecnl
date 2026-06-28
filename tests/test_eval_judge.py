"""Tests for the LLM-as-judge verdict parser.

The Claude round trip itself is integration territory (and costs
money); these tests pin the response-parsing behaviour so a wire
change in the prompt template surfaces immediately. The parser is
the only piece of the judge with real branching — the rest is the
anthropic SDK call.
"""

from __future__ import annotations

from tests.evals.judge import JudgeVerdict, parse_verdict


def test_parse_verdict_pass() -> None:
    v = parse_verdict("VERDICT: PASS\nREASON: North Atlantic event is present for the 2025-26 season.")
    assert v == JudgeVerdict(passed=True, reason="North Atlantic event is present for the 2025-26 season.")


def test_parse_verdict_fail() -> None:
    v = parse_verdict("VERDICT: FAIL\nREASON: event list is missing entirely.")
    assert v == JudgeVerdict(passed=False, reason="event list is missing entirely.")


def test_parse_verdict_case_insensitive() -> None:
    # The model occasionally lowercases the labels; the parser must
    # not care so a perfectly valid grading isn't lost to formatting.
    v = parse_verdict("verdict: pass\nreason: matches the criterion.")
    assert v.passed is True
    assert v.reason == "matches the criterion."


def test_parse_verdict_tolerates_leading_whitespace() -> None:
    # Some models prepend a blank line or indent the response.
    v = parse_verdict("\n  VERDICT: PASS\n  REASON: looks right.")
    assert v.passed is True
    assert v.reason == "looks right."


def test_parse_verdict_missing_reason_is_empty_string() -> None:
    v = parse_verdict("VERDICT: PASS")
    assert v.passed is True
    assert v.reason == ""


def test_parse_verdict_unparseable_is_failure() -> None:
    # Defensive default: a malformed response must never silently
    # pass — otherwise a prompt-template regression would mask real
    # failures.
    raw = "I think the output looks fine, generally speaking."
    v = parse_verdict(raw)
    assert v.passed is False
    assert raw in v.reason
