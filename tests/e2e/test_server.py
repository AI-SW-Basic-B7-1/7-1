"""테스트 브라우저에 격리된 SQLite와 결정적인 AI 응답을 제공합니다."""

import os

import uvicorn

from app.main import app
from app.routers import chat_router


async def generate_test_response(question: str, history: list) -> str:
    """외부 AI에 연결하지 않고 화면 검증용 답변을 반환합니다."""
    return f"테스트 AI 응답: {question}"


chat_router.generate_chat_response = generate_test_response


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8765")), log_level="warning")
