"""테스트 전체에서 사용할 운영 설정 격리 fixture."""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def configure_test_jwt(monkeypatch):
    """실제 환경 파일 없이 테스트 전용 JWT 서명 설정을 적용합니다."""
    monkeypatch.setattr(
        settings,
        "SECRET_KEY",
        "unit-test-signing-key-only-000000000000000000000000",
    )
    monkeypatch.setattr(settings, "ALGORITHM", "HS256")


@pytest.fixture
def mock_missing_pet_tour_parameters(monkeypatch):
    """채팅 API 테스트에서 여행 조건 분석 외부 호출을 건너뜁니다."""
    from app.routers import chat_router

    async def extract_missing_parameters(question: str, history: list) -> dict:
        """검색 조건이 없을 때의 테스트 응답을 제공합니다."""
        return {"areaCode": None, "contentTypeId": None}

    monkeypatch.setattr(
        chat_router,
        "extract_pet_tour_parameters",
        extract_missing_parameters,
    )
