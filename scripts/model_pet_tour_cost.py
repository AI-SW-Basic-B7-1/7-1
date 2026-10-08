"""관광 후보 확대의 호출량과 Gemini 비용을 외부 API 없이 비교합니다."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pet_service import CACHE_TTL_SECONDS, CANDIDATE_LIMIT, RECOMMENDATION_LIMIT


def model_cost(
    requests: int,
    local_hits: int,
    parameter_input_tokens: int,
    parameter_output_tokens: int,
    answer_input_tokens: int,
    answer_output_tokens: int,
    input_price: Decimal,
    output_price: Decimal,
) -> dict:
    """주어진 사용량 가정으로 호출·토큰·비용을 계산하며 실제 계측으로 오인하지 않습니다."""
    counts = (requests, local_hits, parameter_input_tokens, parameter_output_tokens,
              answer_input_tokens, answer_output_tokens)
    if any(type(value) is not int or value < 0 for value in counts) or local_hits > requests:
        raise ValueError("요청·토큰 수는 음수가 아니어야 하며 직접 판별 수는 요청 수 이하여야 합니다.")
    if any(not price.is_finite() or price < 0 for price in (input_price, output_price)):
        raise ValueError("가격은 유한한 음수 아닌 값이어야 합니다.")

    def scenario(parameter_calls: int) -> dict:
        """분석 호출 수만 바꾸고 최종 답변의 길이와 문맥은 동일하게 비교합니다."""
        input_tokens = parameter_calls * parameter_input_tokens + requests * answer_input_tokens
        output_tokens = parameter_calls * parameter_output_tokens + requests * answer_output_tokens
        cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
        return {
            "gemini_calls": requests + parameter_calls,
            "input_tokens": input_tokens,
            "output_tokens_including_thoughts": output_tokens,
            "estimated_usd": str(cost),
        }

    return {
        "assumption": (
            f"동일 검색 조건·후보 {CANDIDATE_LIMIT}건·단일 프로세스·순차 실행·"
            f"모든 요청이 {CACHE_TTL_SECONDS}초 캐시 안에서 처리됨·캐시 퇴출 없음·시군구 조회 장애 없음"
        ),
        "baseline": {**scenario(requests), "tour_calls_upper_bound": 11 * requests},
        "improved": {
            **scenario(requests - local_hits),
            "tour_calls_per_cold_request_upper_bound": 2 + 2 * RECOMMENDATION_LIMIT,
            "tour_calls_all_cold_upper_bound": (1 + 2 * RECOMMENDATION_LIMIT) * requests + requests - local_hits,
            "tour_calls_without_sigungu_per_cold_request_upper_bound": 1 + 2 * RECOMMENDATION_LIMIT,
            "tour_calls_same_pool_upper_bound": min(
                (2 + 2 * RECOMMENDATION_LIMIT) * requests, 2 + 2 * CANDIDATE_LIMIT,
            ) if requests else 0,
            "tour_calls_without_sigungu_same_pool_upper_bound": min(
                (1 + 2 * RECOMMENDATION_LIMIT) * requests, 1 + 2 * CANDIDATE_LIMIT,
            ) if requests else 0,
            "tour_calls_fully_warm": 0,
        },
    }


def main() -> None:
    """실측 또는 명시한 가정의 값을 받아 비교 결과를 JSON으로 출력합니다."""
    parser = argparse.ArgumentParser(description="외부 API를 호출하지 않고 관광 검색의 비용을 비교합니다.")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--local-hits", type=int, default=80)
    parser.add_argument("--parameter-input-tokens", type=int, default=2200)
    parser.add_argument("--parameter-output-tokens", type=int, default=64)
    parser.add_argument("--answer-input-tokens", type=int, default=3400)
    parser.add_argument("--answer-output-tokens", type=int, default=1400)
    parser.add_argument("--input-price", type=Decimal, default=Decimal("0.30"))
    parser.add_argument("--output-price", type=Decimal, default=Decimal("2.50"))
    args = parser.parse_args()
    try:
        result = model_cost(**vars(args))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
