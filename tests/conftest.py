import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def configure_test_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """모든 테스트에서 인증용 임시 서명 키를 설정합니다."""
    monkeypatch.setattr(
        settings,
        "SECRET_KEY",
        "test-only-secret-for-unit-and-integration-tests",
    )
