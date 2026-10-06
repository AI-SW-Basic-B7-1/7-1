"""로그 회전 검증이 테스트 EC2 표식 없이 동작하지 않는지 확인합니다."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts/ec2/verify_e2e_log_rotation.sh"


def test_rotation_refuses_to_run_without_test_instance_marker(tmp_path: Path):
    """테스트 EC2 표식이 없으면 logrotate 명령 전에 종료합니다."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("이 검증은 Bash가 설치된 Linux 환경에서 실행합니다.")

    script = tmp_path / "verify_e2e_log_rotation.sh"
    marker = tmp_path / "e2e-test-instance"
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    source = source.replace("/etc/b7-1/e2e-test-instance", marker.as_posix())
    script.write_text(source, encoding="utf-8")

    commands = tmp_path / "commands"
    commands.mkdir()
    driver = commands / "driver"
    driver.write_text(
        f"#!{sys.executable}\n" + textwrap.dedent(
            """
            import os
            import sys
            from pathlib import Path

            command = Path(sys.argv[0]).name
            if command == "id":
                print("0")
            elif command == "logrotate":
                Path(os.environ["LOGROTATE_CALLED"]).write_text("called")
            else:
                raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    driver.chmod(0o755)
    (commands / "id").symlink_to(driver)
    (commands / "logrotate").symlink_to(driver)

    environment = os.environ.copy()
    environment.update(
        PATH=str(commands) + os.pathsep + environment.get("PATH", ""),
        LOGROTATE_CALLED=str(tmp_path / "logrotate-called"),
        VERIFY_BASE_URL="https://example.test",
    )
    result = subprocess.run(
        [bash, str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert "테스트 EC2에서만" in result.stderr
    assert not (tmp_path / "logrotate-called").exists()


def test_chat_events_are_found_after_app_log_rotation(tmp_path: Path):
    """브라우저 요청 이벤트가 앱의 자체 회전 로그에 있어도 검증합니다."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("이 검증은 Bash가 설치된 Linux 환경에서 실행합니다.")

    project = tmp_path / "project"
    script = project / "scripts/ec2/verify_e2e_log_rotation.sh"
    script.parent.mkdir(parents=True)
    marker = tmp_path / "e2e-test-instance"
    marker.write_text("test", encoding="utf-8")
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    source = source.replace("/etc/b7-1/e2e-test-instance", marker.as_posix())
    script.write_text(source, encoding="utf-8")

    app_logs = tmp_path / "app-logs"
    nginx_logs = tmp_path / "nginx-logs"
    app_logs.mkdir()
    nginx_logs.mkdir()
    (app_logs / "app.log").write_text("", encoding="utf-8")
    (nginx_logs / "nginx_access.log").write_text("", encoding="utf-8")
    (app_logs / "app.log.1").write_text(
        "\n".join(
            (
                "INFO request_received user_id=7 path=/api/chat request_id=01234567-89ab-cdef-0123-456789abcdef",
                "INFO ai_call_start user_id=7 request_id=01234567-89ab-cdef-0123-456789abcdef",
                "INFO ai_call_success request_id=01234567-89ab-cdef-0123-456789abcdef latency_ms=12",
                "INFO db_save_success user_id=7 chat_id=4 request_id=01234567-89ab-cdef-0123-456789abcdef",
            )
        ),
        encoding="utf-8",
    )
    logrotate_file = tmp_path / "logrotate.conf"
    logrotate_file.write_text("test", encoding="utf-8")
    commands = tmp_path / "commands"
    commands.mkdir()
    driver = commands / "driver"
    driver.write_text(
        f"#!{sys.executable}\n" + textwrap.dedent(
            """
            import os
            import shutil
            import sys
            from pathlib import Path

            command = Path(sys.argv[0]).name
            arguments = sys.argv[1:]
            if command == "id":
                print("0")
            elif command == "stat":
                print("root:600")
            elif command == "openssl":
                print("0123456789abcdef0123456789abcdef")
            elif command == "sleep":
                pass
            elif command == "curl":
                url = arguments[-1]
                if url.endswith("/latest/api/token"):
                    print("metadata-token", end="")
                elif url.endswith("/latest/meta-data/instance-id"):
                    print("i-0123456789abcdef0", end="")
                else:
                    header_path = Path(arguments[arguments.index("-D") + 1])
                    counter_path = Path(os.environ["CURL_COUNTER"])
                    count = int(counter_path.read_text() or "0") if counter_path.exists() else 0
                    count += 1
                    counter_path.write_text(str(count))
                    request_id = (
                        "11111111-1111-1111-1111-111111111111"
                        if count == 1 else "22222222-2222-2222-2222-222222222222"
                    )
                    header_path.write_text(f"HTTP/2 200\\r\\nX-Request-ID: {request_id}\\r\\n\\r\\n")
                    for path in (
                        Path(os.environ["APP_LOG_DIR"]) / "app.log",
                        Path(os.environ["NGINX_LOG_DIR"]) / "nginx_access.log",
                    ):
                        with path.open("a") as output:
                            output.write(f"INFO http_request_started request_id={request_id}\\n")
                    print("200", end="")
            elif command == "logrotate" and "--force" in arguments:
                for active, rotated in (
                    (Path(os.environ["APP_LOG_DIR"]) / "app.log", Path(os.environ["APP_LOG_DIR"]) / "app.log.1"),
                    (Path(os.environ["NGINX_LOG_DIR"]) / "nginx_access.log", Path(os.environ["NGINX_LOG_DIR"]) / "nginx_access.log.1"),
                ):
                    shutil.copyfile(active, rotated)
                    active.write_text("")
            elif command == "logrotate":
                pass
            else:
                raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    driver.chmod(0o755)
    for command in ("id", "stat", "openssl", "sleep", "curl", "logrotate"):
        (commands / command).symlink_to(driver)

    environment = os.environ.copy()
    environment.update(
        PATH=str(commands) + os.pathsep + environment.get("PATH", ""),
        VERIFY_BASE_URL="https://example.test",
        VERIFY_CHAT_REQUEST_ID="01234567-89ab-cdef-0123-456789abcdef",
        EXPECTED_INSTANCE_ID="i-0123456789abcdef0",
        APP_LOG_DIR=str(app_logs),
        NGINX_LOG_DIR=str(nginx_logs),
        LOGROTATE_FILE=str(logrotate_file),
        CURL_COUNTER=str(tmp_path / "curl-counter"),
    )
    result = subprocess.run(
        [bash, str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "로그 회전 검증 완료" in result.stdout
