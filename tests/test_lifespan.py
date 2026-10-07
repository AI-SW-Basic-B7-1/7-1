"""DB 초기화 실패 시 기동 중단과 복구 동작을 검증합니다."""

from unittest.mock import AsyncMock, Mock

import aiosqlite
import pytest
from fastapi import FastAPI

from app import lifespan


@pytest.mark.anyio
@pytest.mark.parametrize(
    "secret_key",
    ["", "short-test-key", "your_super_secret_jwt_key_here"],
)
async def test_startup_rejects_missing_or_example_secret_key(secret_key, monkeypatch):
    """운영 비밀 키가 없거나 예시값이면 DB 초기화 전 애플리케이션 시작을 거부합니다."""
    initialize = AsyncMock()
    log_error = Mock()
    monkeypatch.setattr(lifespan, "init_db", initialize)
    monkeypatch.setattr(lifespan.settings, "SECRET_KEY", secret_key)
    monkeypatch.setattr(lifespan.settings, "ALGORITHM", "HS256")
    monkeypatch.setattr(lifespan.app_logger, "error", log_error)
    manager = lifespan.AppLifespanManager()

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        await manager.startup()

    assert not manager.is_database_initialized
    initialize.assert_not_awaited()
    log_error.assert_called_once_with("invalid_jwt_configuration")


@pytest.mark.anyio
async def test_startup_rejects_unsupported_jwt_algorithm(monkeypatch):
    """HS256 이외 알고리즘이면 DB 초기화 전에 애플리케이션 시작을 거부합니다."""
    initialize = AsyncMock()
    log_error = Mock()
    monkeypatch.setattr(lifespan, "init_db", initialize)
    monkeypatch.setattr(
        lifespan.settings,
        "SECRET_KEY",
        "unit-test-signing-key-only-000000000000000000000000",
    )
    monkeypatch.setattr(lifespan.settings, "ALGORITHM", "HS384")
    monkeypatch.setattr(lifespan.app_logger, "error", log_error)

    with pytest.raises(RuntimeError, match="ALGORITHM"):
        await lifespan.AppLifespanManager().startup()

    initialize.assert_not_awaited()
    log_error.assert_called_once_with("invalid_jwt_configuration")


@pytest.mark.anyio
async def test_startup_failure_aborts_lifespan_and_allows_recovery(monkeypatch):
    """초기화 실패를 숨기지 않고 기록하며 다음 정상 시작은 허용합니다."""
    initialize = AsyncMock(side_effect=aiosqlite.OperationalError("초기화 실패"))
    log_error = Mock()
    monkeypatch.setattr(lifespan, "init_db", initialize)
    monkeypatch.setattr(lifespan.app_logger, "exception", log_error)
    monkeypatch.setattr(
        lifespan.settings,
        "SECRET_KEY",
        "unit-test-signing-key-only-000000000000000000000000",
    )
    monkeypatch.setattr(lifespan.settings, "ALGORITHM", "HS256")
    manager = lifespan.AppLifespanManager()
    manager.is_database_initialized = True
    entered = False
    with pytest.raises(aiosqlite.OperationalError):
        async with manager.lifespan(FastAPI()):
            entered = True
    assert not entered
    assert not manager.is_database_initialized
    log_error.assert_called_once_with("database_initialization_failed")

    initialize.side_effect = None
    async with manager.lifespan(FastAPI()):
        assert manager.is_database_initialized
    assert not manager.is_database_initialized
