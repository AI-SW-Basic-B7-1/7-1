"""SQLite 데이터베이스 연결, 초기화 및 대화 데이터 접근 모듈."""

from pathlib import Path
from typing import AsyncIterator, Optional

import aiosqlite

from app.config import settings


class ConversationAccessError(Exception):
    """사용자가 접근할 수 없는 대화방에 저장을 시도한 경우의 예외."""


def get_database_path() -> Path:
    """환경설정의 DATABASE_URL에서 SQLite DB 파일 경로를 반환합니다."""
    database_url = settings.DATABASE_URL
    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        raise ValueError("SQLite DATABASE_URL 형식만 지원합니다.")
    return Path(database_url.removeprefix(sqlite_prefix))


async def get_db_connection(
    database_path: Path | str | None = None,
) -> aiosqlite.Connection:
    """SQLite DB 연결 객체를 생성하고 기본 PRAGMA 설정을 적용합니다."""
    target_path = Path(database_path) if database_path else get_database_path()
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


async def _get_table_columns(
    connection: aiosqlite.Connection,
    table_name: str,
) -> set[str]:
    """지정한 테이블에 현재 정의된 열 이름을 반환합니다."""
    cursor = await connection.execute(f"PRAGMA table_info({table_name});")
    return {row["name"] for row in await cursor.fetchall()}


async def _create_conversations_table(connection: aiosqlite.Connection) -> None:
    """주제별 대화방을 저장하는 conversations 테이블을 생성합니다."""
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title VARCHAR(100) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        """
    )


async def _create_chat_logs_table(connection: aiosqlite.Connection) -> None:
    """대화방에 속한 질문과 AI 응답을 저장하는 chat_logs 테이블을 생성합니다."""
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_logs (
            chat_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            response TEXT NOT NULL,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id)
                REFERENCES conversations(conversation_id) ON DELETE CASCADE
        );
        """
    )


async def _migrate_legacy_schema(connection: aiosqlite.Connection) -> None:
    """기존 사용자와 대화 기록을 새 주제별 대화 구조로 이전합니다."""
    user_columns = await _get_table_columns(connection, "users")
    if "id" in user_columns and "user_id" not in user_columns:
        await connection.execute("ALTER TABLE users RENAME COLUMN id TO user_id;")

    await _create_conversations_table(connection)
    chat_columns = await _get_table_columns(connection, "chat_logs")
    if not chat_columns:
        await _create_chat_logs_table(connection)
        return

    if "user_id" in chat_columns and "conversation_id" not in chat_columns:
        await connection.execute("ALTER TABLE chat_logs RENAME TO chat_logs_legacy;")
        await _create_chat_logs_table(connection)
        await connection.execute(
            """
            INSERT INTO conversations (user_id, title, created_at, updated_at)
            SELECT user_id, '이전 대화', MIN(created_at), MAX(created_at)
            FROM chat_logs_legacy
            GROUP BY user_id;
            """
        )
        await connection.execute(
            """
            INSERT INTO chat_logs (
                chat_log_id,
                conversation_id,
                question,
                response,
                latency_ms,
                created_at
            )
            SELECT
                legacy.id,
                conversation.conversation_id,
                legacy.question,
                legacy.response,
                legacy.latency_ms,
                legacy.created_at
            FROM chat_logs_legacy AS legacy
            JOIN conversations AS conversation
                ON conversation.user_id = legacy.user_id
               AND conversation.title = '이전 대화';
            """
        )
        await connection.execute("DROP TABLE chat_logs_legacy;")
    elif "id" in chat_columns and "chat_log_id" not in chat_columns:
        await connection.execute(
            "ALTER TABLE chat_logs RENAME COLUMN id TO chat_log_id;"
        )


async def init_db(database_path: Path | str | None = None) -> None:
    """애플리케이션 시작 시 테이블, 마이그레이션 및 인덱스를 구성합니다."""
    connection = await get_db_connection(database_path)
    try:
        await connection.execute("PRAGMA foreign_keys = OFF;")
        await connection.execute("BEGIN IMMEDIATE;")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await _migrate_legacy_schema(connection)
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
            ON conversations (user_id, updated_at DESC);
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_logs_conversation_created
            ON chat_logs (conversation_id, created_at ASC);
            """
        )
        # 외래키 검사를 끈 동안 이전한 데이터도 커밋 전에 검증합니다.
        async with connection.execute("PRAGMA foreign_key_check;") as cursor:
            violation = await cursor.fetchone()
        if violation is not None:
            raise RuntimeError("DB 초기화 중 외래키 무결성 위반을 발견했습니다.")
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.execute("PRAGMA foreign_keys = ON;")
        await connection.close()


async def get_user_by_username(
    connection: aiosqlite.Connection,
    username: str,
) -> Optional[aiosqlite.Row]:
    """사용자 아이디로 사용자 정보를 한 건 조회합니다."""
    cursor = await connection.execute(
        "SELECT user_id, username FROM users WHERE username = ?;",
        (username,),
    )
    return await cursor.fetchone()


async def create_conversation(
    connection: aiosqlite.Connection,
    user_id: int,
    title: str,
) -> int:
    """사용자의 새 대화방을 만들고 대화방 고유 번호를 반환합니다."""
    normalized_title = title.strip()[:100] or "새 대화"
    cursor = await connection.execute(
        "INSERT INTO conversations (user_id, title) VALUES (?, ?);",
        (user_id, normalized_title),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("생성된 대화방 식별자를 확인할 수 없습니다.")
    return cursor.lastrowid


async def conversation_belongs_to_user(
    connection: aiosqlite.Connection,
    conversation_id: int,
    user_id: int,
) -> bool:
    """대화방이 현재 사용자 소유인지 확인합니다."""
    cursor = await connection.execute(
        """
        SELECT 1 FROM conversations
        WHERE conversation_id = ? AND user_id = ?;
        """,
        (conversation_id, user_id),
    )
    return await cursor.fetchone() is not None


async def get_recent_chat_logs_by_conversation(
    connection: aiosqlite.Connection,
    conversation_id: int,
    limit: int = 5,
) -> list[aiosqlite.Row]:
    """대화방의 최근 기록을 오래된 순서로 반환합니다."""
    cursor = await connection.execute(
        """
        SELECT question, response
        FROM chat_logs
        WHERE conversation_id = ?
        ORDER BY created_at DESC, chat_log_id DESC
        LIMIT ?;
        """,
        (conversation_id, limit),
    )
    return list(reversed(await cursor.fetchall()))


async def save_chat_log(
    connection: aiosqlite.Connection,
    user_id: int,
    question: str,
    response: str,
    latency_ms: int,
    conversation_id: int | None = None,
) -> tuple[int, int]:
    """사용자 소유 대화방에 질문과 AI 응답을 저장합니다."""
    try:
        if conversation_id is None:
            conversation_id = await create_conversation(
                connection,
                user_id,
                question,
            )
        else:
            if not await conversation_belongs_to_user(
                connection, conversation_id, user_id
            ):
                raise ConversationAccessError("접근할 수 있는 대화방을 찾지 못했습니다.")

        cursor = await connection.execute(
            """
            INSERT INTO chat_logs (
                conversation_id,
                question,
                response,
                latency_ms
            )
            VALUES (?, ?, ?, ?);
            """,
            (conversation_id, question, response, latency_ms),
        )
        await connection.execute(
            """
            UPDATE conversations
            SET updated_at = CURRENT_TIMESTAMP
            WHERE conversation_id = ?;
            """,
            (conversation_id,),
        )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise

    if cursor.lastrowid is None:
        raise RuntimeError("저장된 대화 기록 식별자를 확인할 수 없습니다.")
    return cursor.lastrowid, conversation_id


async def get_chat_logs_by_user(
    connection: aiosqlite.Connection,
    user_id: int,
) -> list[aiosqlite.Row]:
    """사용자의 대화 기록을 대화방 정보와 함께 최신순으로 조회합니다."""
    cursor = await connection.execute(
        """
        SELECT
            chat.chat_log_id,
            chat.conversation_id,
            conversation.title,
            chat.question,
            chat.response,
            chat.latency_ms,
            chat.created_at
        FROM chat_logs AS chat
        JOIN conversations AS conversation
            ON conversation.conversation_id = chat.conversation_id
        WHERE conversation.user_id = ?
        ORDER BY chat.created_at DESC, chat.chat_log_id DESC;
        """,
        (user_id,),
    )
    return await cursor.fetchall()
