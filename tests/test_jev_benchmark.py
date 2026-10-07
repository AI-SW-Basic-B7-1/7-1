"""Jev 비교 지표의 분모와 예시 사례 형식을 확인합니다."""

from pathlib import Path

from scripts.benchmark_jev import load_cases, summarize


def test_false_accept_uses_human_nonaccept_cases():
    """잘못 수용한 비율은 사람이 비수용으로 본 사례만 분모로 삼습니다."""
    accuracy, false_accept = summarize([
        ("accept", "retry"),
        ("retry", "retry"),
        ("accept", "accept"),
    ])
    assert round(accuracy, 1) == 66.7
    assert false_accept == 50.0


def test_example_cases_load_without_quality_claim():
    """예시 JSONL은 비교 도구의 입력 형식으로만 사용됩니다."""
    cases = load_cases(Path("tests/fixtures/jev_cases.jsonl"))
    assert len(cases) == 3
    assert all(case["expected_action"] in {"accept", "retry", "review"} for case in cases)
