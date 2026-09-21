"""FastAPI 애플리케이션 Pydantic 요청 및 응답 데이터 스키마 정의 모듈.

본 모듈은 프론트엔드와 백엔드 간 통신 규약(API Contract)을 정의하며,
클라이언트 요청 데이터의 자동 유효성 검증 및 Swagger UI 대화형 API 문서 생성을 담당합니다.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================================
# 1. 인증 관련 스키마 (Authentication Schemas)
# ============================================================================

class UserRegisterRequest(BaseModel):
    """신규 사용자 회원가입 요청 스키마."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="사용자 로그인 아이디 (3자 이상 50자 이하)",
    )
    password: str = Field(
        ...,
        min_length=4,
        max_length=100,
        description="사용자 로그인 비밀번호 (최소 4자 이상)",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """아이디의 공백 여부를 검증하고 앞뒤 공백을 제거합니다."""
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("아이디는 공백일 수 없습니다.")
        if len(trimmed) < 3:
            raise ValueError("아이디는 최소 3자 이상이어야 합니다.")
        return trimmed

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """비밀번호의 공백 여부를 검증합니다."""
        if not value or not value.strip():
            raise ValueError("비밀번호는 공백일 수 없습니다.")
        return value

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "codyssey123",
                "password": "password1234",
            }
        }
    )


class UserRegisterResponse(BaseModel):
    """신규 사용자 회원가입 성공 응답 스키마."""

    message: str = Field(
        default="회원가입이 완료되었습니다.",
        description="회원가입 성공 안내 메시지",
    )
    username: str = Field(
        ...,
        description="등록 완료된 사용자 계정 아이디",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "회원가입이 완료되었습니다.",
                "username": "codyssey123",
            }
        }
    )


class UserLoginRequest(BaseModel):
    """사용자 로그인 및 토큰 발급 요청 스키마."""

    username: str = Field(
        ...,
        description="사용자 로그인 아이디",
    )
    password: str = Field(
        ...,
        description="사용자 로그인 비밀번호",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """로그인 아이디의 앞뒤 공백을 제거하고 빈 문자열을 검증합니다."""
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("아이디를 입력해 주세요.")
        return trimmed

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """로그인 비밀번호 입력을 검증합니다."""
        if not value:
            raise ValueError("비밀번호를 입력해 주세요.")
        return value

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "codyssey123",
                "password": "password1234",
            }
        }
    )


class TokenResponse(BaseModel):
    """로그인 성공 시 반환되는 JWT 액세스 토큰 응답 스키마."""

    access_token: str = Field(
        ...,
        description="JWT 기반 인증 액세스 토큰 문자열",
    )
    token_type: str = Field(
        default="bearer",
        description="토큰 인증 방식 (기본값: bearer)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
            }
        }
    )


class TokenData(BaseModel):
    """JWT 토큰 디코딩 및 검증 결과 보관용 스키마."""

    username: Optional[str] = Field(
        default=None,
        description="토큰 페이로드에서 추출한 사용자 계정 아이디",
    )


# ============================================================================
# 2. AI 챗봇 대화 관련 스키마 (Chat Schemas)
# ============================================================================

class ChatRequest(BaseModel):
    """AI 챗봇 질문 전송 요청 스키마."""

    question: str = Field(
        ...,
        max_length=500,
        description="사용자가 질문할 텍스트 내용 (최대 500자)",
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """질문 문자열의 앞뒤 공백을 제거합니다."""
        return value.strip()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "이번 주 프로젝트 4일 일정 요약해줘.",
            }
        }
    )


class ChatResponse(BaseModel):
    """AI 챗봇 질문에 대한 응답 반환 스키마."""

    answer: str = Field(
        ...,
        description="AI 모델이 생성한 답변 내용",
    )
    latency_ms: int = Field(
        ...,
        ge=0,
        description="AI 호출 및 응답 처리에 소요된 시간 (밀리초 단위)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": "이번 주 4일 프로토타입 프로젝트 일정은 Day 1 독립 모듈 세팅, Day 2 코어 로직 완성, Day 3 E2E 결합, Day 4 안정성 점검 및 배포 순서로 진행됩니다.",
                "latency_ms": 520,
            }
        }
    )


class ChatLogItem(BaseModel):
    """사용자의 개별 대화 이력 로그 단일 항목 스키마."""

    id: int = Field(
        ...,
        description="대화 이력 식별자 (PK)",
    )
    question: str = Field(
        ...,
        description="사용자가 입력했던 질문 내용",
    )
    response: str = Field(
        ...,
        description="AI가 생성했던 답변 내용",
    )
    latency_ms: int = Field(
        default=0,
        ge=0,
        description="답변 생성 소요 시간 (밀리초)",
    )
    created_at: datetime = Field(
        ...,
        description="대화 기록 생성 일시 (ISO 8601 형식)",
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "question": "안녕? 너는 누구야?",
                "response": "안녕하세요! AI 어시스턴트입니다.",
                "latency_ms": 420,
                "created_at": "2026-09-15T20:45:00",
            }
        },
    )


class ChatHistoryResponse(BaseModel):
    """대화 이력 목록 응답 래퍼 스키마 (필요 시 목록 감싸기 용도)."""

    chats: List[ChatLogItem] = Field(
        default_factory=list,
        description="사용자의 대화 이력 목록",
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "chats": [
                    {
                        "id": 1,
                        "question": "안녕?",
                        "response": "안녕하세요! AI 어시스턴트입니다.",
                        "latency_ms": 420,
                        "created_at": "2026-09-15T20:45:00",
                    }
                ]
            }
        },
    )


# ============================================================================
# 3. 공통 시스템 및 오류 응답 스키마 (System & Error Schemas)
# ============================================================================

class HealthResponse(BaseModel):
    """서버 헬스체크 응답 스키마."""

    status: str = Field(
        default="ok",
        description="서버 가용 상태 (정상: ok)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
            }
        }
    )


class ErrorDetailResponse(BaseModel):
    """서버 공통 오류 응답 상세 스키마."""

    detail: str = Field(
        ...,
        description="오류 발생 상세 원인 메시지",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "아이디 또는 비밀번호가 올바르지 않습니다.",
            }
        }
    )
