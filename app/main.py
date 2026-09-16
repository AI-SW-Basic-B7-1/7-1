"""FastAPI 애플리케이션 메인 진입점 모듈.

본 모듈은 API 서버 인스턴스를 생성하고, 라우터와 정적 파일 서빙,
헬스체크, 애플리케이션 시작 시 초기화 작업을 통합합니다.
"""

from contextlib import asynccontextmanager
from inspect import isawaitable
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers.auth_router import router as auth_router
from app.routers.chat_router import router as chat_router
from app.schemas import HealthResponse


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"


def create_app() -> FastAPI:
    """FastAPI 앱 인스턴스를 생성하고 공통 설정을 등록합니다."""
    fastapi_app = FastAPI(
        title="AI Assistant API",
        description="웹 기반 AI 챗봇 서비스 백엔드 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    configure_cors(fastapi_app)
    register_routers(fastapi_app)
    mount_static_files(fastapi_app)
    register_system_routes(fastapi_app)

    return fastapi_app


# app/database.py 구현 후 명시적 init_db import 방식으로 수정
async def _run_optional_startup_hook() -> None:
    """DB 초기화 함수가 준비된 경우에만 실행합니다."""
    try:
        from app import database
    except ImportError:
        return

    init_db: Optional[Callable[..., Any]] = getattr(database, "init_db", None)
    if init_db is None:
        return

    result = init_db()
    if isawaitable(result):
        await result


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작과 종료 시점의 공통 작업을 관리합니다."""
    await _run_optional_startup_hook()
    yield


def configure_cors(app: FastAPI) -> None:
    """로컬 개발 환경에서 필요한 CORS 정책을 등록합니다."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5500",
            "http://127.0.0.1:5500",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


def register_routers(app: FastAPI) -> None:
    """기능별 API 라우터를 앱에 등록합니다."""
    app.include_router(auth_router)
    app.include_router(chat_router)


def mount_static_files(app: FastAPI) -> None:
    """프론트엔드 정적 파일 디렉터리를 앱에 연결합니다."""
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def register_system_routes(app: FastAPI) -> None:
    """루트 페이지와 서버 상태 확인 라우트를 등록합니다."""

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        """프론트엔드 메인 HTML 파일을 반환합니다."""
        return FileResponse(INDEX_HTML)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health_check() -> HealthResponse:
        """서버 상태 확인용 헬스체크 응답을 반환합니다."""
        return HealthResponse(status="ok")

    @app.get("/api/health", response_model=HealthResponse, tags=["system"])
    async def api_health_check() -> HealthResponse:
        """API 경로 기반 서버 상태 확인 응답을 반환합니다."""
        return HealthResponse(status="ok")


app = create_app()
