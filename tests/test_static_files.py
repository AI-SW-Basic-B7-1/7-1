"""FastAPI 웹 화면과 정적 파일 제공 경로를 검증합니다."""

import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_homepage_and_referenced_static_files_are_served():
    """메인 HTML과 HTML에서 참조하는 모든 정적 파일이 HTTP 200을 반환합니다."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        homepage = await client.get("/")
        assert homepage.status_code == 200

        static_paths = set(
            re.findall(r'(?:href|src)="(/static/[^\"]+)"', homepage.text)
        )
        assert "/static/css/style.css" in static_paths
        assert "/static/js/auth.js" in static_paths

        for static_path in static_paths:
            response = await client.get(static_path)
            assert response.status_code == 200, static_path
            assert response.content, static_path
