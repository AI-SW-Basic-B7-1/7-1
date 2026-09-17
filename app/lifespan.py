"""FastAPI 애플리케이션 생명주기 관리 모듈.

본 모듈은 서버 시작 시 필요한 초기화 작업을 main.py 밖에서 관리합니다.
현재는 SQLite 데이터베이스 테이블 및 WAL 모드 초기화를 담당합니다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db


class AppLifespanManager:
    """애플리케이션 시작 및 종료 시 실행할 작업을 관리하는 클래스."""

    def __init__(self) -> None:
        """생명주기 관리자 인스턴스를 초기화합니다."""
        self.is_database_initialized = False

    async def startup(self) -> None:
        """애플리케이션 시작 시 SQLite DB를 초기화합니다."""
        await init_db()
        self.is_database_initialized = True

    async def shutdown(self) -> None:
        """애플리케이션 종료 시 필요한 정리 작업을 수행합니다."""
        self.is_database_initialized = False

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """FastAPI lifespan 설정에 전달할 생명주기 컨텍스트를 제공합니다."""
        await self.startup()
        try:
            yield
        finally:
            await self.shutdown()


lifespan_manager = AppLifespanManager()
app_lifespan = lifespan_manager.lifespan
