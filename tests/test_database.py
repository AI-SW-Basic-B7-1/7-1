"""주제별 대화 SQLite 스키마와 데이터 마이그레이션 검증 모듈."""

import aiosqlite
import pytest

from app.database import get_db_connection, init_db, save_chat_log


async def get_column_names(
    connection: aiosqlite.Connection,
    table_name: str,
) -> list[str]:
    """테스트 대상 테이블의 열 이름을 정의 순서대로 반환합니다."""
    cursor = await connection.execute(f"PRAGMA table_info({table_name});")
    return [row["name"] for row in await cursor.fetchall()]


@pytest.mark.anyio
async def test_init_db_creates_topic_based_schema(tmp_path):
    """새 DB가 사용자, 대화방, 대화 기록 구조로 생성되는지 검증합니다."""
    database_path = tmp_path / "topic_chat.db"
    await init_db(database_path)
    await init_db(database_path)
    connection = await get_db_connection(database_path)
    try:
        assert await get_column_names(connection, "users") == [
            "user_id",
            "username",
            "hashed_password",
            "created_at",
        ]
        assert await get_column_names(connection, "conversations") == [
            "conversation_id",
            "user_id",
            "title",
            "created_at",
            "updated_at",
        ]
        assert await get_column_names(connection, "chat_logs") == [
            "chat_log_id",
            "conversation_id",
            "question",
            "response",
            "latency_ms",
            "created_at",
        ]
    finally:
        await connection.close()


@pytest.mark.anyio
async def test_save_chat_log_groups_messages_by_conversation(tmp_path):
    """같은 대화방 번호를 전달하면 질문이 동일한 주제로 묶이는지 검증합니다."""
    database_path = tmp_path / "grouped_chat.db"
    await init_db(database_path)
    connection = await get_db_connection(database_path)
    try:
        cursor = await connection.execute(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?);",
            ("owner", "테스트 해시"),
        )
        user_id = cursor.lastrowid
        assert user_id is not None

        first_log_id, conversation_id = await save_chat_log(
            connection,
            user_id,
            "AWS 배포 방법",
            "첫 번째 답변",
            100,
        )
        second_log_id, continued_id = await save_chat_log(
            connection,
            user_id,
            "Nginx 설정 방법",
            "두 번째 답변",
            120,
            conversation_id,
        )

        assert first_log_id != second_log_id
        assert continued_id == conversation_id
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM chat_logs WHERE conversation_id = ?;",
            (conversation_id,),
        )
        assert (await cursor.fetchone())[0] == 2
    finally:
        await connection.close()


@pytest.mark.anyio
async def test_save_chat_log_rejects_another_users_conversation(tmp_path):
    """다른 사용자가 소유한 대화방에는 기록을 저장할 수 없는지 검증합니다."""
    database_path = tmp_path / "isolated_chat.db"
    await init_db(database_path)
    connection = await get_db_connection(database_path)
    try:
        await connection.executemany(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?);",
            [("owner", "테스트 해시"), ("intruder", "테스트 해시")],
        )
        await connection.commit()
        cursor = await connection.execute(
            "SELECT user_id FROM users ORDER BY user_id;"
        )
        owner_id, intruder_id = [row[0] for row in await cursor.fetchall()]
        _, conversation_id = await save_chat_log(
            connection,
            owner_id,
            "소유자의 질문",
            "소유자의 답변",
            50,
        )

        with pytest.raises(ValueError):
            await save_chat_log(
                connection,
                intruder_id,
                "접근 시도",
                "저장되면 안 되는 답변",
                50,
                conversation_id,
            )
    finally:
        await connection.close()


@pytest.mark.anyio
async def test_init_db_migrates_legacy_chat_records(tmp_path):
    """기존 사용자와 대화 기록이 새 대화방 구조로 보존되는지 검증합니다."""
    database_path = tmp_path / "legacy_chat.db"
    async with aiosqlite.connect(database_path) as connection:
        await connection.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                response TEXT NOT NULL,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            INSERT INTO users (username, hashed_password)
            VALUES ('legacy_user', '테스트 해시');
            INSERT INTO chat_logs (user_id, question, response, latency_ms)
            VALUES (1, '기존 질문', '기존 답변', 90);
            """
        )
        await connection.commit()

    await init_db(database_path)
    connection = await get_db_connection(database_path)
    try:
        cursor = await connection.execute(
            """
            SELECT
                user.user_id,
                conversation.title,
                chat.chat_log_id,
                chat.question,
                chat.response
            FROM users AS user
            JOIN conversations AS conversation
                ON conversation.user_id = user.user_id
            JOIN chat_logs AS chat
                ON chat.conversation_id = conversation.conversation_id;
            """
        )
        row = await cursor.fetchone()
        assert tuple(row) == (1, "이전 대화", 1, "기존 질문", "기존 답변")
        cursor = await connection.execute("PRAGMA foreign_key_check;")
        assert await cursor.fetchall() == []
    finally:
        await connection.close()
