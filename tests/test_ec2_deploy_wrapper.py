"""SSM 배포 명령 생성과 중단 복구 계약을 검증합니다."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def generate_remote_command(bash, project_dir, repo_url, expected_sha="", deploy_script=None):
    """실제 배포 스크립트에서 원격 명령 생성 부분을 실행합니다."""
    source = (PROJECT_ROOT / "scripts/ec2/run_ec2_deploy.sh").read_text(encoding="utf-8")
    marker = 'remote_command="$(\n'
    start = source.index(marker) + len(marker)
    end = source.index('\n)"\n\n# Windows용 AWS CLI', start)
    values = {
        "clone_dir_q": str(project_dir),
        "project_dir_q": str(project_dir),
        "repo_url_q": str(repo_url),
        "branch_q": "main",
        "secret_parameter_q": "/test/environment",
        "region_q": "ap-northeast-2",
        "app_user_q": "ubuntu",
        "deploy_script_q": str(deploy_script or project_dir / "scripts/ec2/deploy_ec2.sh"),
        "clone_parent_q": str(project_dir.parent),
    }
    assignments = "\n".join(
        f"{name}={shlex.quote(shlex.quote(value))}" for name, value in values.items()
    )
    result = subprocess.run(
        [bash],
        input=(
            assignments
            + f"\nDEPLOY_SHA={shlex.quote(expected_sha)}\nRUN_TESTS=0\n"
            + source[start:end]
        ),
        text=True,
        capture_output=True,
        check=True,
        env=dict(os.environ, LC_ALL="C"),
    )
    return result.stdout


def test_acme_webroot_is_created_before_certificate_request():
    """Certbot 실행 전 웹루트 소유권과 접근 권한을 설정합니다."""
    source = (PROJECT_ROOT / "scripts/ec2/deploy_ec2.sh").read_text(encoding="utf-8")
    create_step = "run_cmd 'ACME 챌린지 웹루트 생성' install -d -o root -g www-data -m 2755 /var/www/certbot"
    certificate_step = "run_cmd 'Let’s Encrypt 인증서 발급·갱신' certbot certonly --webroot"

    assert source.index(create_step) < source.index(certificate_step)


@pytest.mark.parametrize("service_was_active", [False, True])
def test_sigterm_runs_remote_rollback_and_restores_service_state(tmp_path, service_was_active):
    """생성된 원격 명령이 TERM을 받은 배포를 정리하고 서비스 상태를 복원합니다."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash가 필요한 원격 명령 생성 테스트입니다.")
    try:
        subprocess.run(
            [bash, "--version"],
            capture_output=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pytest.skip("현재 실행 환경에서 Bash를 시작할 수 없습니다.")

    generated = generate_remote_command(
        bash, tmp_path, "https://example.invalid/repository.git"
    )

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


@pytest.fixture
def revision_deployment(tmp_path):
    """실제 Git 이력과 외부 서비스의 테스트 대역을 준비합니다."""
    bash = shutil.which("bash")
    git = shutil.which("git")
    if not bash or not git:
        pytest.skip("Bash와 Git이 필요한 테스트입니다.")
    origin = tmp_path / "origin"
    origin.mkdir()

    def git_run(*args, cwd=origin):
        """테스트 전용 Git 명령을 실행합니다."""
        return subprocess.run(
            [git, *args], cwd=cwd, text=True, capture_output=True, check=True
        ).stdout.strip()

    git_run("init", "-b", "main")
    git_run("config", "user.name", "배포 테스트")
    git_run("config", "user.email", "deployment-test@example.invalid")
    (origin / ".gitignore").write_text(".env\nlogs/\n", encoding="utf-8")
    (origin / "requirements.txt").write_text("", encoding="utf-8")
    script = origin / "scripts/ec2/deploy_ec2.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        '#!/usr/bin/env bash\nmkdir -p "$PROJECT_DIR/logs"\n'
        'printf "배포 실행\\n" >> "$TEST_CALLS"\n'
        'if [[ "$CHANGE_SHA" == 1 ]]; then git -C "$PROJECT_DIR" checkout --detach "$NEW_SHA"; fi\n',
        encoding="utf-8",
    )
    git_run("add", ".")
    git_run("commit", "-m", "test: 이전 배포")
    previous_sha = git_run("rev-parse", "HEAD")
    (origin / "version.txt").write_text("배포 대상\n", encoding="utf-8")
    git_run("add", ".")
    git_run("commit", "-m", "test: 트리거 커밋")
    target_sha = git_run("rev-parse", "HEAD")
    (origin / "version.txt").write_text("진행된 main\n", encoding="utf-8")
    git_run("add", ".")
    git_run("commit", "-m", "test: 후속 커밋")
    newest_sha = git_run("rev-parse", "HEAD")
    git_run("checkout", "-b", "other")
    (origin / "other.txt").write_text("다른 브랜치\n", encoding="utf-8")
    git_run("add", ".")
    git_run("commit", "-m", "test: 배포 브랜치 밖의 커밋")
    other_sha = git_run("rev-parse", "HEAD")
    git_run("checkout", "main")
    project = tmp_path / "배포 폴더"
    commands = tmp_path / "commands"
    commands.mkdir()
    stubs = {
        "install": 'mkdir -p "${@: -1}"\n',
        "chown": "exit 0\n",
        "aws": 'printf "환경 파일 조회\\n" >> "$TEST_CALLS"\nprintf "TEST_ENV=1\\n"\n',
        "systemctl": 'printf "systemctl %s\\n" "$*" >> "$TEST_CALLS"\n[[ "$1" != is-active ]]\n',
    }
    for name, body in stubs.items():
        command = commands / name
        command.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        command.chmod(0o755)
    calls = tmp_path / "calls.log"
    environment = dict(
        os.environ,
        PATH=str(commands) + os.pathsep + os.environ.get("PATH", ""),
        TEST_CALLS=str(calls),
        CHANGE_SHA="0",
        NEW_SHA=newest_sha,
    )
    return bash, git_run, origin, project, previous_sha, target_sha, newest_sha, other_sha, calls, environment


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("pin_revision", [False, True])
def test_deployment_revision_with_advanced_main(revision_deployment, existing, pin_revision):
    """main이 진행된 뒤에도 지정 커밋을 배포하고 수동 브랜치 배포를 유지합니다."""
    bash, git_run, origin, project, previous, target, newest, _, calls, env = revision_deployment
    if existing:
        git_run("clone", str(origin), str(project))
        git_run("checkout", "--detach", previous, cwd=project)
    expected = target if pin_revision else newest
    generated = generate_remote_command(bash, project, origin, target if pin_revision else "")
    result = subprocess.run([bash], input=generated, text=True, capture_output=True, env=env, timeout=15)
    assert result.returncode == 0, result.stderr
    assert git_run("rev-parse", "HEAD", cwd=project) == expected
    assert (project / "logs/deployed_revision.txt").read_text().strip() == expected
    assert f"배포 성공 SHA: {expected}" in result.stdout
    assert "배포 실행" in calls.read_text()


def test_revision_outside_main_stops_before_environment_and_deployment(revision_deployment):
    """다른 브랜치의 커밋은 코드와 환경을 변경하기 전에 거부합니다."""
    bash, git_run, origin, project, previous, _, _, other, calls, env = revision_deployment
    git_run("clone", str(origin), str(project))
    git_run("checkout", "--detach", previous, cwd=project)
    result = subprocess.run(
        [bash], input=generate_remote_command(bash, project, origin, other),
        text=True, capture_output=True, env=env, timeout=15,
    )
    assert result.returncode != 0
    assert git_run("rev-parse", "HEAD", cwd=project) == previous
    assert "환경 파일 조회" not in calls.read_text()
    assert "배포 실행" not in calls.read_text()


def test_revision_change_during_deployment_rolls_back(revision_deployment):
    """배포 중 SHA가 바뀌면 실패 처리하고 이전 코드와 환경을 복원합니다."""
    bash, git_run, origin, project, previous, target, _, _, calls, env = revision_deployment
    git_run("clone", str(origin), str(project))
    git_run("checkout", "--detach", previous, cwd=project)
    (project / ".env").write_text("PREVIOUS_ENV=1\n", encoding="utf-8")
    env["CHANGE_SHA"] = "1"
    result = subprocess.run(
        [bash], input=generate_remote_command(bash, project, origin, target),
        text=True, capture_output=True, env=env, timeout=15,
    )
    assert result.returncode != 0
    assert "배포 중 커밋 SHA가 변경되었습니다." in result.stderr
    assert git_run("rev-parse", "HEAD", cwd=project) == previous
    assert (project / ".env").read_text() == "PREVIOUS_ENV=1\n"
    assert not (project / "logs/deployed_revision.txt").exists()
    assert "배포 성공 SHA:" not in result.stdout


@pytest.mark.parametrize("sha", ["main", "a" * 39, "A" * 40, "a" * 40 + ";echo invalid"])
def test_invalid_revision_is_rejected_before_aws(sha, tmp_path):
    """불완전하거나 명령을 포함한 SHA를 AWS 호출 전에 차단합니다."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash가 필요한 테스트입니다.")
    result = subprocess.run(
        [bash, str(PROJECT_ROOT / "scripts/ec2/run_ec2_deploy.sh"),
         "--instance-id", "i-test", "--repo-url", "https://example.invalid/repo.git",
         "--secret-parameter", "/test/environment", "--commit-sha", sha],
        text=True, capture_output=True, env=dict(os.environ, LOCAL_LOG_DIR=str(tmp_path)),
    )
    assert result.returncode != 0
    assert "40자리 커밋 SHA" in result.stderr
    assert not list(tmp_path.iterdir())
