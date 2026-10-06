"""로컬 대역과 실제 배포 E2E의 실행 경계를 확인하는 픽스처입니다."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from secrets import token_hex
from urllib.parse import urlsplit

import pytest

from tests.e2e.helpers import E2EAccount


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def validate_e2e_target(mode: str, configured_url: str) -> str:
    """실행 모드와 대상 URL이 섞이지 않도록 검증합니다."""
    url = configured_url.rstrip("/")
    if mode not in {"local", "deployment"}:
        raise ValueError("E2E_MODE는 local 또는 deployment여야 합니다.")
    if mode == "local":
        if url:
            raise ValueError("E2E_BASE_URL을 사용하려면 deployment 모드를 지정해야 합니다.")
        return ""
    if not url:
        raise ValueError("배포 E2E에는 HTTPS E2E_BASE_URL이 필요합니다.")

    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("E2E_BASE_URL 포트 형식이 올바르지 않습니다.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("배포 대상은 경로·인증정보 없는 HTTPS 도메인이어야 합니다.")
    return url


def pytest_addoption(parser: pytest.Parser) -> None:
    """E2E 모드와 시나리오 선택 옵션을 등록합니다."""
    group = parser.getgroup("b7-1-e2e")
    group.addoption("--e2e-mode", choices=("local", "deployment"), default=None)
    group.addoption("--e2e-scenarios", default="")


def pytest_configure(config: pytest.Config) -> None:
    """시나리오와 배포 전용 테스트 표식을 등록합니다."""
    config.addinivalue_line("markers", "e2e_scenario(identifier): 실행 시나리오 식별자")
    config.addinivalue_line("markers", "deployment_only: 실제 배포 환경에서만 실행")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """JUnit 결과에 테스트가 검증하는 시나리오 번호를 기록합니다."""
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("e2e_scenario")
    identifiers = [str(value) for value in marker.args] if marker else []
    alias = os.environ.get("E2E_SCENARIO_ALIAS", "").strip()
    if alias:
        identifiers.append(alias)
    if identifiers:
        report.user_properties.append(
            ("e2e_scenario", ",".join(identifiers))
        )


def _mode(config: pytest.Config) -> str:
    """명령행 옵션 또는 환경 변수에서 실행 모드를 반환합니다."""
    return config.getoption("--e2e-mode") or os.environ.get("E2E_MODE", "local")


def pytest_sessionstart(session: pytest.Session) -> None:
    """잘못된 배포 설정이면 테스트 수집 전에 중단합니다."""
    mode = _mode(session.config)
    try:
        validate_e2e_target(mode, os.environ.get("E2E_BASE_URL", ""))
    except ValueError as exc:
        pytest.exit(str(exc), returncode=4)
    if mode == "deployment":
        required = ("E2E_RUN_ID", "E2E_ACCOUNT_USERNAME", "E2E_ACCOUNT_PASSWORD")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            pytest.exit("배포 E2E 필수 설정 누락: " + ", ".join(missing), returncode=4)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """요청한 시나리오를 선택하고 로컬 모드의 배포 전용 시험을 제외합니다."""
    requested = {
        value.strip()
        for value in config.getoption("--e2e-scenarios").split(",")
        if value.strip()
    }
    selected = []
    deselected = []
    for item in items:
        scenario = item.get_closest_marker("e2e_scenario")
        identifiers = set(scenario.args) if scenario else set()
        if requested and not (requested & identifiers):
            deselected.append(item)
        elif _mode(config) == "local" and item.get_closest_marker("deployment_only"):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.fixture(scope="session")
def e2e_mode(pytestconfig: pytest.Config) -> str:
    """현재 실행 모드를 반환합니다."""
    return _mode(pytestconfig)


@pytest.fixture(scope="session")
def e2e_target(tmp_path_factory, e2e_mode: str):
    """배포 모드의 HTTPS 주소 또는 격리된 로컬 서버를 제공합니다."""
    if e2e_mode == "deployment":
        yield validate_e2e_target(e2e_mode, os.environ["E2E_BASE_URL"])
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


@pytest.fixture(scope="session")
def e2e_account() -> E2EAccount:
    """현재 시험에서 사용할 계정 정보를 메모리에 제공합니다."""
    return E2EAccount({
        "username": os.environ.get("E2E_ACCOUNT_USERNAME", f"e2e_{token_hex(6)}"),
        "password": os.environ.get("E2E_ACCOUNT_PASSWORD", f"E2e_{token_hex(8)}a1"),
    })


@pytest.fixture(scope="session")
def e2e_secondary_account() -> E2EAccount:
    """사용자 격리 시험을 위한 별도 계정을 제공합니다."""
    return E2EAccount({"username": f"e2e_{token_hex(6)}", "password": f"E2e_{token_hex(8)}b2"})


@pytest.fixture(scope="session")
def e2e_state(tmp_path_factory):
    """요청 ID와 질문·답변 해시만 실행 간 비교 파일에 보관합니다."""
    configured_path = os.environ.get("E2E_STATE_FILE", "")
    state_path = (
        Path(configured_path)
        if configured_path
        else tmp_path_factory.mktemp("e2e-state") / "baseline.json"
    )

    def read() -> dict:
        if not state_path.is_file():
            return {}
        return json.loads(state_path.read_text(encoding="utf-8"))

    def write(state: dict) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return {"path": state_path, "read": read, "write": write}


@pytest.fixture
def e2e_record(e2e_mode: str):
    """질문·답변 원문을 제외한 허용 필드만 기록합니다."""
    evidence_path = os.environ.get("E2E_EVIDENCE_FILE", "")
    allowed = {
        "request_id", "status", "conversation_id", "question_sha256",
        "answer_sha256", "elapsed_ms", "history_count", "ui_blocked",
    }

    def record(scenario_id: str, **fields: int | str) -> None:
        if set(fields) - allowed:
            raise ValueError("허용되지 않은 E2E 증거 필드가 있습니다.")
        payload = {"scenario_id": scenario_id, "mode": e2e_mode, **fields}
        if evidence_path:
            path = Path(evidence_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return record
