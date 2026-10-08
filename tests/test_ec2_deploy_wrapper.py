"""SSM 배포 명령 생성과 중단 복구 계약을 검증합니다."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _usable_bash():
    """현재 실행 환경에서 실제 셸 명령을 처리할 수 있는 Bash를 찾습니다."""
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        subprocess.run(
            [bash],
            input="true\n",
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return bash


def test_resolve_database_path_accepts_only_project_local_sqlite_files():
    """배포 경로 검증이 사용자 SQLite 경로와 프로젝트 경계를 동일하게 적용합니다."""
    bash = _usable_bash()
    if not bash:
        pytest.skip("실행 가능한 Bash가 필요한 SQLite 경로 검증입니다.")

    source = (PROJECT_ROOT / "scripts/ec2/deploy_ec2.sh").read_text(encoding="utf-8")
    start = source.index("resolve_database_path() {")
    end = source.index("\n}\n\nlog_step '운영 환경변수", start) + 2
    function = source[start:end]
    project = "/tmp/project"
    script = (
        f"PROJECT_DIR={shlex.quote(project)}\n"
        "fail() { printf '%s\\n' \"$1\" >&2; exit 1; }\n"
        f"{function}\n"
    )

    def resolve(database_url):
        command = script + f"resolve_database_path {shlex.quote(database_url)}\n"
        return subprocess.run(
            [bash],
            input=command,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    relative = resolve("sqlite:///./data/custom.db")
    assert relative.returncode == 0, relative.stderr
    assert Path(relative.stdout).name == "custom.db"
    assert Path(relative.stdout).parent.name == "data"

    absolute = resolve("sqlite:////tmp/project/data/absolute.db")
    assert absolute.returncode == 0, absolute.stderr
    assert Path(absolute.stdout).name == "absolute.db"

    assert resolve("sqlite:////tmp/outside.db").returncode != 0
    assert resolve("postgresql://database").returncode != 0


def test_acme_webroot_is_created_before_certificate_request():
    """Certbot 실행 전 웹루트 소유권과 접근 권한을 설정합니다."""
    source = (PROJECT_ROOT / "scripts/ec2/deploy_ec2.sh").read_text(encoding="utf-8")
    create_step = "run_cmd 'ACME 챌린지 웹루트 생성' install -d -o root -g www-data -m 2755 /var/www/certbot"
    certificate_step = "run_cmd 'Let’s Encrypt 인증서 발급·갱신' certbot certonly --webroot"

    assert source.index(create_step) < source.index(certificate_step)


@pytest.mark.parametrize("service_was_active", [False, True])
def test_sigterm_runs_remote_rollback_and_restores_service_state(tmp_path, service_was_active):
    """생성된 원격 명령이 TERM을 받은 배포를 정리하고 서비스 상태를 복원합니다."""
    bash = _usable_bash()
    if not bash:
        pytest.skip("실행 가능한 Bash가 필요한 원격 명령 생성 테스트입니다.")
    if os.name == "nt" and Path(bash).parent.name.lower() == "windowsapps":
        pytest.skip("WindowsApps Bash가 Windows 임시 경로를 접근할 수 없습니다.")

    source = (PROJECT_ROOT / "scripts/ec2/run_ec2_deploy.sh").read_text(encoding="utf-8")
    marker = 'remote_command="$(\n'
    start = source.index(marker) + len(marker)
    end = source.index('\n)"\n\n# Windows용 AWS CLI', start)
    builder = source[start:end]
    path = str(tmp_path)
    values = {
        "clone_dir_q": path,
        "project_dir_q": path,
        "repo_url_q": "https://example.invalid/repository.git",
        "branch_q": "main",
        "secret_parameter_q": "/test/environment",
        "region_q": "ap-northeast-2",
        "app_user_q": "ubuntu",
        "deploy_script_q": str(tmp_path / "deploy_ec2.sh"),
        "clone_parent_q": str(tmp_path.parent),
    }
    assignments = "\n".join(
        f"{name}={shlex.quote(value)}" for name, value in values.items()
    )
    generation_result = subprocess.run(
        [bash],
        input=(
            assignments
            + "\nRUN_TESTS=0\nquote_for_remote() { printf %q \"$1\"; }\n"
            + builder
            + "\nprintf '%s\\n' \"$remote_command\"\n"
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert generation_result.returncode == 0, generation_result.stderr
    generated = generation_result.stdout

    calls = tmp_path / "calls.log"
    commands = tmp_path / "commands"
    commands.mkdir()
    systemctl = commands / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'systemctl %s\\n' \"$*\" >> \"$TEST_CALLS\"\n"
        "if [[ \"$1\" == is-active ]]; then [[ \"$SERVICE_ACTIVE\" == 1 ]]; exit; fi\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    for name in ("git", "chown"):
        command = commands / name
        command.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '{name} %s\\n' \"$*\" >> \"$TEST_CALLS\"\n",
            encoding="utf-8",
        )
        command.chmod(0o755)

    remote_prefix = generated.split("\ninstall -d -m 755 -o root -g root", 1)[0]
    scenario = (
        "\ncode_updated=1\nprevious_revision=old-revision\nprevious_branch=main\n"
        "sleep 30 &\ndeployment_pid=$!\nkill -0 \"${deployment_pid}\"\nsleep 0.2\nkill -TERM $$\n"
    )
    environment = dict(
        os.environ,
        PATH=str(commands) + os.pathsep + os.environ.get("PATH", ""),
        TEST_CALLS=str(calls),
        SERVICE_ACTIVE="1" if service_was_active else "0",
    )
    result = subprocess.run(
        [bash],
        input=remote_prefix + scenario,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 143
    recorded = calls.read_text(encoding="utf-8")
    assert "git -c safe.directory=" in recorded
    assert "systemctl daemon-reload" in recorded
    service_commands = [
        line for line in recorded.splitlines() if line.startswith("systemctl ")
    ]
    expected_service_command = (
        "systemctl restart chatbot.service"
        if service_was_active
        else "systemctl stop chatbot.service"
    )
    assert service_commands[-1] == expected_service_command
