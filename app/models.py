"""데이터베이스 레코드 엔티티 모델 정의 모듈.

본 모듈은 SQLite 데이터베이스의 users, conversations, chat_logs 테이블 행 데이터를
파이썬 계층에서 안전하게 다루기 위한 Pydantic 데이터 모델을 제공합니다.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class UserInDB(BaseModel):
    """users 테이블에 저장된 사용자 계정 엔티티 모델."""

    user_id: int
    username: str
    hashed_password: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ChatLogInDB(BaseModel):
    """chat_logs 테이블에 저장된 대화 로그 엔티티 모델."""

    chat_log_id: int
    conversation_id: int
    question: str
    response: str
    latency_ms: int = 0
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
