"""DB 초기화 실패 시 기동 중단과 복구 동작을 검증합니다."""

from unittest.mock import AsyncMock, Mock

import aiosqlite
import pytest
from fastapi import FastAPI

from app import lifespan


@pytest.mark.anyio
async def test_startup_failure_aborts_lifespan_and_allows_recovery(monkeypatch):
    """초기화 실패를 숨기지 않고 기록하며 다음 정상 시작은 허용합니다."""
    initialize = AsyncMock(side_effect=aiosqlite.OperationalError("초기화 실패"))
    log_error = Mock()
    monkeypatch.setattr(lifespan, "init_db", initialize)
    monkeypatch.setattr(lifespan.app_logger, "exception", log_error)
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
