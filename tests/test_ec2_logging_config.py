"""EC2 Nginx 로그 설정 스크립트의 보안 계약을 검증합니다."""

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
        f'DROPIN_DIR="{tmp_path}/systemd/${{SERVICE}}.d"',
    ).replace("/var/backups/b7-1-nginx", str(backups))
    assert "/etc/systemd/system/" not in source
    assert "/var/backups/" not in source
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
        mode = os.environ["TEST_MODE"]
        service = os.environ.get("SERVICE_NAME", "chatbot.service")
        dropin = root / ("systemd/" + service + ".d/90-b7-1-logging.conf")
        with (root / "calls").open("a") as output:
            output.write(command + " " + " ".join(args) + "\n")

        if command == "systemctl":
            if args[0] in ("restart", "stop"):
                state = root / (args[-1] + ".active")
                if args[0] == "restart":
                    state.touch()
                else:
                    state.unlink(missing_ok=True)
            if args[0] == "is-active" and (mode == "fresh" or os.environ.get("TEST_INIT_INACTIVE") == "1"):
                sys.exit(0 if (root / (args[-1] + ".active")).exists() else 3)
            if args[0] == "show":
                property_name = args[args.index("-p") + 1]
                if property_name == "WorkingDirectory":
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
            candidate = Path(os.environ["SITE_CONFIG"]).read_text()
            if mode == "invalid_config" and "log_format" in candidate:
                sys.exit(1)
        elif command == "realpath":
            print(Path(args[-1]).resolve())
        elif command == "chmod":
            # macOS에서도 Ubuntu의 옵션 종료 구분자를 처리합니다.
            values = [value for value in args if value != "--"]
            for filename in values[1:]:
                Path(filename).chmod(int(values[0], 8))
        elif command == "install":
            shutil.copyfile(args[-2], args[-1])
            Path(args[-1]).chmod(int(args[args.index("-m") + 1], 8))
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
                with (logs / "nginx_access.log").open("a") as output:
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
    for name in ("nginx", "systemctl", "curl", "realpath", "readlink", "sleep", "chmod", "install"):
        (commands / name).symlink_to(driver)

    def run(mode="success", action=None):
        """실제 파일 편집·백업·복원은 임시 디렉터리에서 수행합니다."""
        env = dict(os.environ)
        env.update(
            PATH=str(commands) + os.pathsep + env.get("PATH", ""),
            SITE_CONFIG=str(site),
            VERIFY_BASE_URL="http://test.local",
            TEST_ROOT=str(tmp_path),
            TEST_MODE=mode,
            TMPDIR=str(tmp_path),
        )
        return subprocess.run(
            [bash, str(script)] + ([action] if action else []),
            env=env, text=True, capture_output=True, timeout=30,
        )

    return run, tmp_path, site, original_site, dropin


def test_prepare_and_verify_do_not_restart_services(script_environment):
    """설정 준비와 검증은 서비스를 재시작하지 않으며 검증은 설정을 변경하지 않습니다."""
    run, root, site, _, dropin = script_environment
    result = run("fresh", "--prepare")
    assert result.returncode == 0, result.stderr
    before = (site.read_bytes(), dropin.read_bytes())
    result = run(action="--verify")
    assert result.returncode == 0, result.stderr
    assert before == (site.read_bytes(), dropin.read_bytes())
    calls = (root / "calls").read_text()
    assert "systemctl restart" not in calls
    assert "systemctl reload" not in calls
    assert "systemctl daemon-reload" not in calls


@pytest.mark.parametrize("site_name,service", [("chatbot", "chatbot.service"), ("travel", "travel.service")])
@pytest.mark.parametrize("failure", ["none", "reapply", "first"])
def test_deploy_configuration_sequence(script_environment, site_name, service, failure):
    """배포의 실제 설정 구간을 실행해 최초 배포·재배포·실패 복원을 확인합니다."""
    _, root, _, _, _ = script_environment
    project = root / "project"
    nginx = root / "nginx"
    for directory in (nginx / "sites-available", nginx / "sites-enabled", root / "systemd"):
        directory.mkdir(parents=True, exist_ok=True)
    source = (SCRIPT_PATH.parent / "deploy_ec2.sh").read_text(encoding="utf-8")
    # 패키지 설치와 DB 작업은 제외하고 설정 트랜잭션 구간을 그대로 실행합니다.
    section = source[source.index('NGINX_AVAILABLE='):source.index("run_cmd 'DB 백업 디렉터리 생성'")]
    section = section.replace("/etc/nginx", str(nginx)).replace("/etc/systemd/system", str(root / "systemd"))
    wrapper = root / "deploy-config.sh"
    wrapper.write_text(
        'set -Eeuo pipefail\nrun_cmd() { shift; "$@"; }\nfail() { exit 1; }\n'
        + section + '\nCONFIG_COMMITTED=1\n', encoding="utf-8",
    )
    site = nginx / "sites-available" / site_name
    unit = root / "systemd" / service
    dropin = root / "systemd" / (service + ".d") / "90-b7-1-logging.conf"
    env = dict(os.environ)
    env.update(
        PATH=str(root / "commands") + os.pathsep + env.get("PATH", ""),
        PROJECT_DIR=str(project), APP_USER="ubuntu", ENV_FILE=str(project / ".env"),
        SERVICE_NAME=service, NGINX_SITE_NAME=site_name,
        SITE_CONFIG=str(site), TEST_ROOT=str(root), TEST_MODE="fresh",
        LOGGING_SCRIPT=str(project / "scripts/ec2/configure_nginx_logs.sh"),
        VERIFY_BASE_URL="http://test.local", TMPDIR=str(root),
    )
    def execute():
        """대역 명령으로 배포 설정 구간을 실행합니다."""
        return subprocess.run([shutil.which("bash"), str(wrapper)], env=env,
                              text=True, capture_output=True, timeout=30)

    if failure == "first":
        env.update(TEST_MODE="query_leak", TEST_INIT_INACTIVE="1")
        result = execute()
        assert result.returncode != 0
        for path in (site, unit, dropin, nginx / "sites-enabled" / site_name):
            assert not path.exists() and not path.is_symlink()
        assert not (root / (service + ".active")).exists()
        assert not (root / "nginx.active").exists()
        return

    for _ in range(2):
        result = execute()
        assert result.returncode == 0, result.stderr
        assert site.read_text().count("log_format b7_1_request_trace") == 1
        assert "location ^~ /logs/" in site.read_text()
    calls = (root / "calls").read_text()
    assert calls.count("systemctl restart " + service) == 2
    assert calls.count("systemctl restart nginx") == 2
    assert "systemctl reload nginx" not in calls
    if failure == "reapply":
        before = [path.read_bytes() for path in (site, unit, dropin)]
        env["TEST_MODE"] = "query_leak"
        result = execute()
        assert result.returncode != 0
        assert "이전 Nginx·systemd 설정으로 복원" in result.stderr
        assert before == [path.read_bytes() for path in (site, unit, dropin)]


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
