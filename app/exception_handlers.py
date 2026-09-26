"""FastAPI 공통 예외 처리 등록 모듈.

본 모듈은 애플리케이션 전역에서 사용할 HTTP 예외, 요청 검증 예외,
미처리 서버 예외 처리기를 한 곳에서 등록합니다.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logger import app_logger
from app.schemas import ErrorDetailResponse


VALIDATION_MESSAGES = {
    ("username", "missing"): "아이디를 입력해 주세요.",
    ("username", "string_type"): "아이디는 문자열로 입력해 주세요.",
    ("username", "string_too_short"): "아이디는 최소 3자 이상이어야 합니다.",
    ("username", "string_too_long"): "아이디는 최대 50자까지 입력할 수 있습니다.",
    ("password", "missing"): "비밀번호를 입력해 주세요.",
    ("password", "string_type"): "비밀번호는 문자열로 입력해 주세요.",
    ("password", "string_too_short"): "비밀번호는 최소 4자 이상이어야 합니다.",
    ("password", "string_too_long"): "비밀번호는 최대 100자까지 입력할 수 있습니다.",
    ("question", "missing"): "질문을 입력해 주세요.",
    ("question", "string_type"): "질문은 문자열로 입력해 주세요.",
    ("question", "string_too_long"): "질문은 최대 500자까지 입력할 수 있습니다.",
    ("conversation_id", "int_type"): "대화방 식별자는 정수로 입력해 주세요.",
    ("conversation_id", "int_parsing"): "대화방 식별자는 정수로 입력해 주세요.",
    ("conversation_id", "greater_than_equal"): "대화방 식별자는 1 이상이어야 합니다.",
}

ALLOWED_VALUE_ERRORS = {
    "아이디는 공백일 수 없습니다.",
    "아이디는 최소 3자 이상이어야 합니다.",
    "아이디를 입력해 주세요.",
    "비밀번호는 공백일 수 없습니다.",
    "비밀번호를 입력해 주세요.",
}


class ExceptionHandlerRegistrar:
    """FastAPI 앱에 공통 예외 처리기를 등록하는 클래스."""

    def __init__(self, app: FastAPI) -> None:
        """예외 처리기를 등록할 FastAPI 앱을 보관합니다."""
        self.app = app

    def register(self) -> None:
        """공통 예외 처리기를 FastAPI 앱에 등록합니다."""
        self.app.add_exception_handler(
            StarletteHTTPException,
            self.http_exception_handler,
        )
        self.app.add_exception_handler(
            RequestValidationError,
            self.validation_exception_handler,
        )
        self.app.add_exception_handler(
            Exception,
            self.unhandled_exception_handler,
        )

    async def http_exception_handler(
        self,
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        """HTTP 예외를 공통 오류 응답 형식으로 반환합니다."""
        return self._build_error_response(
            status_code=exc.status_code,
            detail=str(exc.detail),
            headers=exc.headers,
        )

    async def validation_exception_handler(
        self,
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """요청 데이터 검증 실패를 공통 오류 응답 형식으로 반환합니다."""
        return self._build_error_response(
            status_code=422,
            detail=self._get_validation_detail(exc),
        )

    def _get_validation_detail(self, exc: RequestValidationError) -> str:
        """검증 오류의 필드와 유형을 허용된 한국어 안내 문구로 변환합니다."""
        for error in exc.errors():
            location = error.get("loc", ())
            field = location[-1] if location else None
            error_type = error.get("type", "")
            message = VALIDATION_MESSAGES.get((field, error_type))
            if message:
                return message

            if error_type == "value_error":
                original_error = error.get("ctx", {}).get("error")
                custom_message = str(original_error) if original_error else ""
                if custom_message in ALLOWED_VALUE_ERRORS:
                    return custom_message

        return "요청 데이터 형식이 올바르지 않습니다."

    async def unhandled_exception_handler(
        self,
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """처리되지 않은 서버 예외를 공통 오류 응답 형식으로 반환합니다."""
        if not getattr(request.state, "request_error_logged", False):
            app_logger.exception(
                "unhandled_exception method=%s path=%s error=%s",
                request.method,
                request.url.path,
                exc,
            )
        return self._build_error_response(
            status_code=500,
            detail="서버 내부 오류가 발생했습니다.",
            headers={"X-Request-ID": request.state.request_id}
            if hasattr(request.state, "request_id") else None,
        )

    def _build_error_response(
        self,
        status_code: int,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> JSONResponse:
        """공통 오류 응답 객체를 생성합니다."""
        return JSONResponse(
            status_code=status_code,
            content=ErrorDetailResponse(detail=detail).model_dump(),
            headers=headers,
        )


def register_exception_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 공통 예외 처리기를 등록합니다."""
    ExceptionHandlerRegistrar(app).register()
