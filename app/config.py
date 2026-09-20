"""FastAPI 애플리케이션 환경설정 관리 모듈.

본 모듈은 .env 환경변수 파일 및 시스템 환경변수에서 설정값을 로드하며,
설정값이 누락된 경우 안전한 기본값(Default)을 제공합니다.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 경로 (.env 위치) 탐색 및 로드
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()


class Settings:
    """애플리케이션 전역 설정 클래스."""

    # [JWT 보안 설정]
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "your_super_secret_jwt_key_here_codessey_b7_1_security_default",
    )
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # [데이터베이스 경로 설정]
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/chatbot.db")

    # [Gemini AI API 설정]
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    AI_TIMEOUT_SECONDS: float = float(os.getenv("AI_TIMEOUT_SECONDS", "8.0"))


# 전역 설정 싱글톤 인스턴스
settings = Settings()
