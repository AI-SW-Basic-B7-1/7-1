"""로컬 대역 또는 명시적인 E2E 주소에서 브라우저 테스트를 실행합니다."""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from secrets import token_hex

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def e2e_target(tmp_path_factory):
    """원격 주소 또는 임시 SQLite를 사용하는 로컬 FastAPI 주소를 제공합니다."""
    configured_url = os.environ.get("E2E_BASE_URL", "").rstrip("/")
    if configured_url:
        yield configured_url
        return

    database_path = tmp_path_factory.mktemp("browser-e2e") / "chatbot.db"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "SECRET_KEY": "local-e2e-only-secret-not-for-deployment",
            "GEMINI_API_KEY": "local-e2e-no-network",
        }
    )

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    environment["E2E_PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.e2e.test_server"],
        cwd=PROJECT_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    target_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30

    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("E2E 테스트 서버가 기동하지 못했습니다.")
            try:
                with urllib.request.urlopen(f"{target_url}/api/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        else:
            raise RuntimeError("E2E 테스트 서버의 준비 시간이 초과되었습니다.")

        yield target_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture
def e2e_account():
    """실행마다 구별되는 테스트 전용 계정 정보를 제공합니다."""
    return {
        "username": os.environ.get("E2E_ACCOUNT_USERNAME", f"e2e_{token_hex(6)}"),
        "password": os.environ.get(
            "E2E_ACCOUNT_PASSWORD",
            f"E2e_{token_hex(8)}a1",
        ),
    }
