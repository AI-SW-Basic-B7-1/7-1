"""EC2 Nginx 로그 설정 스크립트의 보안 계약을 검증합니다."""

import getpass
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ec2"
    / "configure_nginx_logs.sh"
)


def test_access_log_excludes_query_and_request_headers():
    """접근 로그가 쿼리·Referer 대신 요청 경로와 처리 결과만 기록하는지 확인합니다."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    format_line = next(
        line for line in source.splitlines()
        if "log_format b7_1_request_trace" in line
    )

    assert "$request_method" in format_line
    assert "$uri" in format_line
    assert "$server_protocol" in format_line
    assert "$upstream_http_x_request_id" in format_line
    assert "$request_id" in format_line
    assert "$request_uri" not in format_line
    assert "$args" not in format_line
    assert "$http_referer" not in format_line
    assert "$http_user_agent" not in format_line
    assert re.search(r"(?<![A-Za-z_])\$request(?![A-Za-z_])", format_line) is None


@pytest.fixture
def script_environment(tmp_path):
    """권한 검사와 운영 경로만 치환한 복사본을 대역 명령으로 실행합니다."""
    bash = shutil.which("bash")
    if not bash or not shutil.which("openssl"):
        pytest.skip("Bash와 OpenSSL이 필요한 셸 실행 테스트입니다.")

    project = tmp_path / "project"
    script = project / "scripts/ec2/configure_nginx_logs.sh"
    script.parent.mkdir(parents=True)
    dropin_dir = tmp_path / "systemd/chatbot.service.d"
    dropin = dropin_dir / "90-b7-1-logging.conf"
    nginx_logs = tmp_path / "nginx-logs"
    logrotate_file = tmp_path / "logrotate/b7-1"
    logrotate_file.parent.mkdir(parents=True)
    backups = tmp_path / "backups"
    site = tmp_path / "site.conf"
    original_site = "server {\n    listen 80;\n    location / { proxy_pass http://127.0.0.1:8000; }\n}\n"
    site.write_text(original_site, encoding="utf-8")

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    guard = '[[ $EUID -eq 0 ]] || { printf \'%s\\n\' \'sudo로 실행해 주세요.\' >&2; exit 1; }'
    assert source.count(guard) == 1
    source = source.replace(guard, ":")
    source = source.replace(
        'DROPIN_DIR="/etc/systemd/system/${SERVICE}.d"',
        f'DROPIN_DIR="{dropin_dir}"',
    ).replace("/var/backups/b7-1-nginx", str(backups))
    source = source.replace(
        "LOGROTATE_FILE='/etc/logrotate.d/b7-1'",
        f"LOGROTATE_FILE='{logrotate_file}'",
    )
    assert "/etc/systemd/system/" not in source
    assert "/var/backups/" not in source
    assert "/etc/logrotate.d/" not in source
    script.write_text(source, encoding="utf-8")

    commands = tmp_path / "commands"
    commands.mkdir()
    driver = commands / "driver"
    driver.write_text(f"#!{sys.executable}\n" + textwrap.dedent(r'''
        import os
        import shutil
        import sys
        import uuid
        from pathlib import Path
        from urllib.parse import urlsplit, parse_qs

        command = Path(sys.argv[0]).name
        args = sys.argv[1:]
        root = Path(os.environ["TEST_ROOT"])
        project = root / "project"
        logs = project / "logs"
        nginx_logs = Path(os.environ["NGINX_LOG_DIR"])
        nginx_logs.mkdir(parents=True, exist_ok=True)
        mode = os.environ["TEST_MODE"]
        dropin = root / "systemd/chatbot.service.d/90-b7-1-logging.conf"
        with (root / "calls").open("a") as output:
            output.write(command + " " + " ".join(args) + "\n")

        if command == "systemctl":
            if args[0] == "show":
                property_name = args[args.index("-p") + 1]
                if property_name == "User":
                    print(os.environ["TEST_APP_USER"])
                elif property_name == "WorkingDirectory":
                    print(project)
                elif property_name == "MainPID":
                    print("12345")
                else:
                    prefix = property_name + "="
                    for line in dropin.read_text().splitlines():
                        if line.startswith(prefix):
                            value = line[len(prefix):]
                            if property_name == "StandardOutput":
                                value = value.split(":", 1)[0]
                            print(value)
        elif command == "readlink":
            print(logs / ("wrong.log" if mode == "wrong_output_path" else "server.log"))
        elif command == "nginx":
            candidate = (root / "site.conf").read_text()
            if mode == "invalid_config" and "log_format" in candidate:
                sys.exit(1)
        elif command == "realpath":
            print(Path(args[-1]).resolve())
        elif command == "install":
            values = list(args)
            mode_value = None
            while values and values[0].startswith("-"):
                option = values.pop(0)
                if option in ("-o", "-g", "-m"):
                    value = values.pop(0)
                    if option == "-m":
                        mode_value = int(value, 8)
            if len(values) != 2:
                sys.exit(2)
            source_path, target_path = map(Path, values)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            if mode_value is not None:
                target_path.chmod(mode_value)
        elif command in ("chown", "logrotate"):
            pass
        elif command == "id":
            if len(args) > 1 and args[1] != os.environ["TEST_APP_USER"]:
                sys.exit(1)
        elif command == "chmod":
            # macOS에서도 Ubuntu의 옵션 종료 구분자를 처리합니다.
            values = [value for value in args if value != "--"]
            for filename in values[1:]:
                Path(filename).chmod(int(values[0], 8))
        elif command == "curl":
            url = urlsplit(args[-1])
            if url.path == "/api/health":
                probe = parse_qs(url.query)["probe"][0]
                with (root / "probes").open("a") as output:
                    output.write(probe + "\n")
                request_id = str(uuid.uuid4())
                header_id = "invalid" if mode == "invalid_header" else request_id
                headers = Path(args[args.index("-D") + 1])
                headers.write_text("HTTP/1.1 200 OK\r\nX-Request-ID: " + header_id + "\r\n\r\n")
                status = "302" if mode == "redirect" else "200"
                access_id = "other" if mode == "access_mismatch" else request_id
                app_id = "other" if mode == "app_mismatch" else request_id
                nginx_id = "a" * (33 if mode == "invalid_nginx_id" else 32)
                key = "client_request_id" if mode == "prefixed_id" else "request_id"
                event = "http_request_started" if mode == "app_incomplete" else "http_request_completed"
                with (logs / "app.log").open("a") as output:
                    output.write(event + " request_id=" + app_id + "\n")
                with (nginx_logs / "nginx_access.log").open("a") as output:
                    # 다른 요청에 같은 검사 문자열이 남아 있는 상황을 재현합니다.
                    output.write("old request_id=old query=" + probe + "\n")
                    output.write("method=GET path=/api/health status=200 " + key + "=" + access_id + " nginx_request_id=" + nginx_id)
                    if mode == "query_leak":
                        output.write(" query=" + probe)
                    if mode == "referer_leak":
                        output.write(" referer=" + args[args.index("-H") + 1])
                    output.write("\n")
                print(status, end="")
            else:
                print("200" if mode == "logs_exposed" else "404", end="")
        elif command != "sleep":
            sys.exit(2)
    '''), encoding="utf-8")
    driver.chmod(0o755)
    for name in (
        "nginx", "systemctl", "curl", "realpath", "readlink", "sleep", "chmod",
        "install", "chown", "logrotate", "id",
    ):
        (commands / name).symlink_to(driver)

    def run(mode="success"):
        """실제 파일 편집·백업·복원은 임시 디렉터리에서 수행합니다."""
        env = dict(os.environ)
        env.update(
            PATH=str(commands) + os.pathsep + env.get("PATH", ""),
            SITE_CONFIG=str(site),
            NGINX_LOG_DIR=str(nginx_logs),
            VERIFY_BASE_URL="http://test.local",
            APP_USER=getpass.getuser(),
            TEST_APP_USER=getpass.getuser(),
            TEST_ROOT=str(tmp_path),
            TEST_MODE=mode,
            TMPDIR=str(tmp_path),
        )
        return subprocess.run(
            [bash, str(script)], env=env, text=True, capture_output=True, timeout=30,
        )

    return run, tmp_path, site, original_site, dropin


def test_script_applies_and_reapplies_with_distinct_probes(script_environment):
    """다른 요청에 같은 문자열이 있어도 성공하고 재실행 시 설정을 중복하지 않습니다."""
    run, root, site, _, dropin = script_environment
    for _ in range(2):
        result = run()
        assert result.returncode == 0, result.stderr
        assert "검증 완료" in result.stdout
    assert site.read_text().count("log_format b7_1_request_trace") == 1
    assert site.read_text().count("location = /logs") == 1
    assert "StandardOutput=append:" in dropin.read_text()
    probes = (root / "probes").read_text().splitlines()
    assert len(probes) == len(set(probes)) == 2
    calls = (root / "calls").read_text()
    for path in ("/logs", "/logs/", "/logs/app.log", "/logs/app.log.1",
                 "/logs/server.log", "/logs/nginx_access.log"):
        assert f"http://test.local{path}\n" in calls


@pytest.mark.parametrize("mode", [
    "query_leak", "referer_leak", "access_mismatch", "app_mismatch",
    "prefixed_id", "app_incomplete", "invalid_nginx_id", "invalid_header",
    "logs_exposed", "redirect", "invalid_config", "wrong_output_path",
])
@pytest.mark.parametrize("existing_dropin", [False, True])
def test_failed_verification_restores_settings(script_environment, mode, existing_dropin):
    """검증 실패 시 기존 설정을 복원하고 새 드롭인 파일은 제거합니다."""
    run, root, site, original_site, dropin = script_environment
    original_dropin = "[Service]\nStandardOutput=journal\nStandardError=journal\n"
    if existing_dropin:
        dropin.parent.mkdir(parents=True)
        dropin.write_text(original_dropin, encoding="utf-8")
    result = run(mode)
    assert result.returncode != 0
    assert "검증 완료" not in result.stdout
    assert site.read_text() == original_site
    if existing_dropin:
        assert dropin.read_text() == original_dropin
    else:
        assert not dropin.exists()
    assert "설정을 복원했습니다." in result.stderr
    calls = (root / "calls").read_text()
    assert "systemctl reload nginx" in calls
    if mode != "invalid_config":
        assert calls.count("systemctl restart chatbot.service") == 2
        assert calls.count("systemctl daemon-reload") == 2
