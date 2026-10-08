"""애플리케이션 환경 설정의 기본값과 범위를 검증합니다."""

import runpy
from pathlib import Path

import pytest

from app.config import _positive_integer, _positive_timeout_seconds


def test_settings_defaults_match_current_runtime_contract(monkeypatch):
    """코드 기본값이 15초 API 제한과 60분 토큰 만료를 유지합니다."""
    for name in (
        "AI_TIMEOUT_SECONDS",
        "PET_TOUR_API_TIMEOUT_SECONDS",
        "ACCESS_TOKEN_EXPIRE_MINUTES",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)
    config_path = Path(__file__).resolve().parents[1] / "app/config.py"
    settings = runpy.run_path(str(config_path))["settings"]

    assert settings.AI_TIMEOUT_SECONDS == 15.0
    assert settings.PET_TOUR_API_TIMEOUT_SECONDS == 15.0
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 60


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "잘못된 값"])
def test_positive_timeout_uses_default_for_invalid_value(monkeypatch, value):
    """양수가 아닌 타임아웃 설정은 안전한 기본값으로 되돌립니다."""
    monkeypatch.setenv("TEST_TIMEOUT_SECONDS", value)

    assert _positive_timeout_seconds("TEST_TIMEOUT_SECONDS", 15.0) == 15.0


def test_positive_timeout_accepts_override(monkeypatch):
    """양수 타임아웃 설정은 지정한 값으로 적용합니다."""
    monkeypatch.setenv("TEST_TIMEOUT_SECONDS", "12.5")

    assert _positive_timeout_seconds("TEST_TIMEOUT_SECONDS", 15.0) == 12.5


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "잘못된 값"])
def test_positive_integer_uses_default_for_invalid_value(monkeypatch, value):
    """양의 정수가 아닌 JWT 만료 설정은 안전한 기본값으로 되돌립니다."""
    monkeypatch.setenv("TEST_TOKEN_MINUTES", value)

    assert _positive_integer("TEST_TOKEN_MINUTES", 60) == 60


def test_positive_integer_accepts_override(monkeypatch):
    """양의 정수 JWT 만료 설정은 지정한 값으로 적용합니다."""
    monkeypatch.setenv("TEST_TOKEN_MINUTES", "30")

    assert _positive_integer("TEST_TOKEN_MINUTES", 60) == 30
