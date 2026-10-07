"""사람이 판정한 동일 사례로 현행 수용과 Jev 판정을 비교합니다."""

import argparse
import asyncio
import json
import sys
from math import ceil
from pathlib import Path
from statistics import mean
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.jev_service import JEV_ACTIONS, JevServiceError, judge_answer


def load_cases(path: Path) -> list[dict]:
    """질문·답변·사람 판정 라벨이 있는 JSONL 사례를 검증해 읽습니다."""
    cases = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("question"), str)
                or not isinstance(item.get("answer"), str)
                or not isinstance(item.get("expected_action"), str)
                or item["expected_action"] not in JEV_ACTIONS
                or not isinstance(item.get("history", []), list)
                or any(
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("question"), str)
                    or not isinstance(entry.get("response"), str)
                    for entry in item.get("history", [])
                )
            ):
                raise ValueError(f"{line_number}행의 사례 형식이 올바르지 않습니다.")
            cases.append(item)
    if not cases:
        raise ValueError("평가 사례가 비어 있습니다.")
    return cases


def summarize(predictions: list[tuple[str, str]]) -> tuple[float, float]:
    """판정 일치율과 비수용 정답에서 잘못 수용한 비율을 계산합니다."""
    accuracy = sum(actual == expected for actual, expected in predictions) / len(predictions)
    nonaccept = [(actual, expected) for actual, expected in predictions if expected != "accept"]
    false_accept = (
        sum(actual == "accept" for actual, _ in nonaccept) / len(nonaccept)
        if nonaccept else 0.0
    )
    return accuracy * 100, false_accept * 100


async def run_benchmark(cases: list[dict], repeat: int) -> None:
    """오류 시 답변을 그대로 통과시키는 실제 shadow 흐름으로 비교합니다."""
    off_predictions = []
    model_predictions = []
    shadow_predictions = []
    latencies = []
    errors = 0

    for _ in range(repeat):
        for item in cases:
            expected = item["expected_action"]
            off_predictions.append(("accept", expected))
            started_at = perf_counter()
            try:
                decision = await judge_answer(
                    item["question"], item.get("history", []), item["answer"]
                )
                actual = decision.action
                model_predictions.append((actual, expected))
            except JevServiceError:
                errors += 1
                actual = "accept"
            latencies.append((perf_counter() - started_at) * 1000)
            shadow_predictions.append((actual, expected))

    off_accuracy, off_false_accept = summarize(off_predictions)
    shadow_accuracy, shadow_false_accept = summarize(shadow_predictions)
    ordered = sorted(latencies)
    p95 = ordered[ceil(len(ordered) * 0.95) - 1]
    print("판정 분류 비교입니다. shadow는 사용자 답변을 변경하지 않습니다.")
    print("Mode     Cases  Decision Acc  False Accept  Avg JEV  P95 JEV  Errors")
    print(f"off*     {len(off_predictions):>5}  {off_accuracy:>11.1f}%  {off_false_accept:>11.1f}%        -        -       -")
    if model_predictions:
        model_accuracy, model_false_accept = summarize(model_predictions)
        print(
            f"model    {len(model_predictions):>5}  {model_accuracy:>11.1f}%"
            f"  {model_false_accept:>11.1f}%        -        -       -"
        )
    print(
        f"effective {len(shadow_predictions):>5}  {shadow_accuracy:>11.1f}%"
        f"  {shadow_false_accept:>11.1f}%  {mean(latencies):>6.0f}ms"
        f"  {p95:>6.0f}ms  {errors:>6}"
    )
    print("* off는 모든 답변을 accept하는 현재 기준선입니다.")
    print("model은 성공 호출만, effective는 실패 시 accept 통과까지 포함합니다.")
    if len(cases) < 30:
        print("주의: 30건 미만의 예시 사례로는 품질 개선을 주장할 수 없습니다.")


def main() -> int:
    """명령행 인자를 읽고 실제 API 비교를 실행합니다."""
    parser = argparse.ArgumentParser(description="Jev 관찰 모드 비교")
    parser.add_argument("--cases", type=Path, default=Path("tests/fixtures/jev_cases.jsonl"))
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat는 1 이상이어야 합니다.")
    if not settings.TYPESAFE_API_KEY:
        print("TYPESAFE_API_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2
    try:
        cases = load_cases(args.cases)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"사례를 읽지 못했습니다: {exc}", file=sys.stderr)
        return 2
    asyncio.run(run_benchmark(cases, args.repeat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
