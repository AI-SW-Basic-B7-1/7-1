"""외부 호출 없는 비용 모델의 계산과 가정을 검증합니다."""

from decimal import Decimal

import pytest

from scripts.model_pet_tour_cost import model_cost


def test_cost_model_keeps_answer_budget_and_reduces_only_parameter_calls():
    """최종 답변 토큰을 줄였다고 가정하지 않고 실제 분석 생략 횟수만 반영합니다."""
    result = model_cost(100, 80, 2200, 64, 3400, 1400, Decimal("0.30"), Decimal("2.50"))
    assert result["baseline"]["estimated_usd"] == "0.534"
    assert result["improved"]["estimated_usd"] == "0.4684"
    assert result["improved"]["gemini_calls"] == 120
    assert result["improved"]["tour_calls_same_pool_upper_bound"] == 42
    assert result["improved"]["input_tokens"] == 100 * 3400 + 20 * 2200


@pytest.mark.parametrize("requests,local_hits,price", [
    (-1, 0, "0.30"), (1, 2, "0.30"), (1, 0, "NaN"), (1, 0, "-1"),
])
def test_cost_model_rejects_invalid_assumptions(requests, local_hits, price):
    """잘못된 횟수와 가격은 계산 결과로 출력하지 않습니다."""
    with pytest.raises(ValueError):
        model_cost(requests, local_hits, 0, 0, 0, 0, Decimal(price), Decimal("2.50"))


def test_zero_requests_has_zero_calls_and_cost():
    """빈 작업량에는 캐시 초기화 비용을 가정하지 않습니다."""
    result = model_cost(0, 0, 0, 0, 0, 0, Decimal("0.30"), Decimal("2.50"))
    assert result["improved"]["tour_calls_same_pool_upper_bound"] == 0
    assert Decimal(result["improved"]["estimated_usd"]) == 0
