"""SQLite 데이터베이스 연결 및 초기화 모듈.

본 모듈은 애플리케이션에서 사용할 SQLite 연결을 생성하고,
서비스 실행에 필요한 users, chat_logs 테이블을 초기화합니다.
"""

from pathlib import Path
from typing import AsyncIterator, Optional

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


async def get_db_connection() -> aiosqlite.Connection:
    """SQLite DB 연결 객체를 생성하고 기본 PRAGMA 설정을 적용합니다."""
    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = await aiosqlite.connect(database_path)
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


async def init_db() -> None:
    """애플리케이션 시작 시 필요한 테이블과 WAL 모드를 초기화합니다."""
    connection = await get_db_connection()
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


async def get_user_by_username(
    connection: aiosqlite.Connection,
    username: str,
) -> Optional[aiosqlite.Row]:
    """사용자 아이디로 사용자 정보를 한 건 조회합니다."""
    cursor = await connection.execute(
        "SELECT id, username FROM users WHERE username = ?;",
        (username,),
    )
    return await cursor.fetchone()


async def save_chat_log(
    connection: aiosqlite.Connection,
    user_id: int,
    question: str,
    response: str,
    latency_ms: int,
) -> int:
    """질문과 AI 응답을 저장하고 생성된 대화 식별자를 반환합니다."""
    try:
        cursor = await connection.execute(
            """
            INSERT INTO chat_logs (user_id, question, response, latency_ms)
            VALUES (?, ?, ?, ?);
            """,
            (user_id, question, response, latency_ms),
        )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise

    if cursor.lastrowid is None:
        raise RuntimeError("저장된 대화 식별자를 확인할 수 없습니다.")
    return cursor.lastrowid


async def get_chat_logs_by_user(
    connection: aiosqlite.Connection,
    user_id: int,
) -> list[aiosqlite.Row]:
    """지정한 사용자의 대화 이력을 최신순으로 조회합니다."""
    cursor = await connection.execute(
        """
        SELECT id, question, response, latency_ms, created_at
        FROM chat_logs
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC;
        """,
        (user_id,),
    )
    return await cursor.fetchall()
