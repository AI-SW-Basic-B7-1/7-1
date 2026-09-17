"""SQLite 데이터베이스 연결 및 초기화 모듈.

본 모듈은 애플리케이션에서 사용할 SQLite 연결을 생성하고,
서비스 실행에 필요한 users, chat_logs 테이블을 초기화합니다.
"""

from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from app.config import settings


def get_database_path() -> Path:
    """환경설정의 DATABASE_URL에서 SQLite DB 파일 경로를 반환합니다."""
    database_url = settings.DATABASE_URL
    sqlite_prefix = "sqlite:///"

    if not database_url.startswith(sqlite_prefix):
        raise ValueError("SQLite DATABASE_URL 형식만 지원합니다.")

    database_path = database_url.removeprefix(sqlite_prefix)
    return Path(database_path)


async def get_db_connection(database_path: Path | str | None = None) -> aiosqlite.Connection:
    """SQLite DB 연결 객체를 생성하고 기본 PRAGMA 설정을 적용합니다."""
    if database_path is None:
        target_path = get_database_path()
    else:
        target_path = Path(database_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    connection = await aiosqlite.connect(target_path)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON;")
    await connection.execute("PRAGMA journal_mode = WAL;")
    return connection


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """FastAPI 의존성에서 사용할 SQLite 연결을 제공합니다."""
    connection = await get_db_connection()
    try:
        yield connection
    finally:
        await connection.close()


async def init_db(database_path: Path | str | None = None) -> None:
    """애플리케이션 시작 시 필요한 테이블과 WAL 모드를 초기화합니다."""
    connection = await get_db_connection(database_path)
    try:
        await connection.execute("PRAGMA journal_mode = WAL;")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                response TEXT NOT NULL,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_logs_user_created
            ON chat_logs (user_id, created_at DESC);
            """
        )
        await connection.commit()
    finally:
        await connection.close()
