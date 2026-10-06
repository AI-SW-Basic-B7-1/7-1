"""SSM으로만 활성화하는 임시 DB 장애·Gemini 문맥 관측 진입점입니다."""

import hashlib
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import httpx


FAULT_MODE = os.environ.get("B7_1_E2E_FAULT_MODE", "")
CONTEXT_FILE = os.environ.get("B7_1_E2E_CONTEXT_FILE", "")
FAULT_ACTIVE = False


if FAULT_MODE in {"db-read", "db-write"}:
    _original_connect = aiosqlite.connect

    async def _guarded_connect(*args, **kwargs):
        """채팅 테이블의 지정된 읽기 또는 삽입만 거부하는 연결을 반환합니다."""
        connection = await _original_connect(*args, **kwargs)

        def authorize(action, first, second, database, trigger):
            """SQLite 작성자 콜백에서 지정 동작만 거부합니다."""
            if not FAULT_ACTIVE:
                return sqlite3.SQLITE_OK
            if FAULT_MODE == "db-read" and action == sqlite3.SQLITE_READ and first == "chat_logs":
                return sqlite3.SQLITE_DENY
            if FAULT_MODE == "db-write" and action == sqlite3.SQLITE_INSERT and first == "chat_logs":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        await connection.set_authorizer(authorize)
        return connection

    aiosqlite.connect = _guarded_connect


if FAULT_MODE == "observe-context":
    context_path = Path(CONTEXT_FILE).resolve(strict=False)
    try:
        context_path.relative_to(Path("/var/lib/b7-1/e2e").resolve())
    except ValueError as exc:
        raise RuntimeError("문맥 관측 결과 경로가 허용 범위에 없습니다.") from exc
    if not CONTEXT_FILE:
        raise RuntimeError("문맥 관측 결과 경로가 허용 범위에 없습니다.")

    _original_async_client = httpx.AsyncClient

    async def _record_context(request: httpx.Request) -> None:
        """Gemini로 실제 전송하는 역할과 본문 해시만 보호 경로에 기록합니다."""
        if request.url.host != "generativelanguage.googleapis.com":
            return
        body = json.loads(request.content)
        contents = body.get("contents", [])
        observed = []
        for item in contents:
            parts = item.get("parts", [])
            if len(parts) != 1 or not isinstance(parts[0].get("text"), str):
                raise RuntimeError("문맥 관측에서 알 수 없는 Gemini 본문 형식을 확인했습니다.")
            observed.append(
                {
                    "role": item.get("role"),
                    "sha256": hashlib.sha256(parts[0]["text"].encode("utf-8")).hexdigest(),
                }
            )
        target = context_path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(observed, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(target)

    class _ObservedAsyncClient(_original_async_client):
        """기존 HTTPX 동작에 요청 직전의 안전한 문맥 관측만 추가합니다."""

        def __init__(self, *args, **kwargs):
            event_hooks = dict(kwargs.pop("event_hooks", {}) or {})
            event_hooks["request"] = [*event_hooks.get("request", []), _record_context]
            super().__init__(*args, event_hooks=event_hooks, **kwargs)

    httpx.AsyncClient = _ObservedAsyncClient


if FAULT_MODE not in {"db-read", "db-write", "observe-context"}:
    raise RuntimeError("지원하지 않는 임시 E2E 실행 모드입니다.")


from app.main import app

if FAULT_MODE in {"db-read", "db-write"}:
    _original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _fault_lifespan(application):
        """앱 초기화가 끝난 뒤에만 요청 경로의 SQLite 장애를 활성화합니다."""
        global FAULT_ACTIVE
        async with _original_lifespan(application) as state:
            FAULT_ACTIVE = True
            try:
                yield state
            finally:
                FAULT_ACTIVE = False

    app.router.lifespan_context = _fault_lifespan
