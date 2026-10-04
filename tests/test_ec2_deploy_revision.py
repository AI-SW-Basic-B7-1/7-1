"""EC2 배포 실행기가 검증한 Git 커밋 SHA를 원격 명령에 전달하는지 확인합니다."""

import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = PROJECT_ROOT / "scripts/ec2/run_ec2_deploy.sh"


@pytest.fixture
def fake_aws(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """외부 AWS를 호출하지 않고 배포 명령을 받아 기록하는 AWS CLI를 제공합니다."""
    bash_path = shutil.which("bash")
    if not bash_path:
        pytest.skip("이 검증은 Bash가 설치된 Linux 환경에서 실행합니다.")

    command_capture = tmp_path / "ssm_command.b64"
    aws_program = tmp_path / "aws"
    aws_program.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "arguments = sys.argv[1:]\n"
        "if arguments[:2] == ['sts', 'get-caller-identity']:\n"
        "    print('arn:aws:iam::000000000000:role/e2e-test')\n"
        "elif arguments[:2] == ['ssm', 'describe-instance-information']:\n"
        "    print('Online')\n"
        "elif arguments[:2] == ['ssm', 'send-command']:\n"
        "    parameters = arguments[arguments.index('--parameters') + 1]\n"
        "    command = parameters.partition('commands=')[2].partition(' | base64 --decode')[0]\n"
        "    pathlib.Path(os.environ['E2E_SSM_CAPTURE']).write_text(command.split()[-1])\n"
        "    print('test-command-id')\n"
        "elif arguments[:2] == ['ssm', 'get-command-invocation']:\n"
        "    query = arguments[arguments.index('--query') + 1]\n"
        "    print({'Status': 'Success', 'StandardOutputContent': '검증 완료', 'StandardErrorContent': 'None'}.get(query, 'None'))\n"
        "else:\n"
        "    raise SystemExit('Unexpected AWS CLI operation')\n",
        encoding="utf-8",
    )
    aws_program.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"
    environment["REPO_URL"] = "https://example.test/codyssey/b7-1.git"
    environment["LOCAL_LOG_DIR"] = str(tmp_path)
    environment["E2E_SSM_CAPTURE"] = str(command_capture)
    return environment, command_capture


def test_revision_is_checked_before_aws_is_used(tmp_path: Path, fake_aws):
    """잘못된 커밋 SHA는 인증 및 AWS 명령을 실행하기 전에 거부합니다."""
    environment, _ = fake_aws
    result = subprocess.run(
        [
            shutil.which("bash") or "bash",
            str(DEPLOY_SCRIPT),
            "--instance-id",
            "i-00000000000000001",
            "--secret-parameter",
            "/b7-1/e2e/environment",
            "--revision",
            "invalid-sha",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert "--revision은 40자리 Git SHA" in result.stderr
    assert not (tmp_path / "ssm_command.b64").exists()


def test_after_start_requires_db_preservation_handshake_before_aws(fake_aws):
    """기동 후 실패 시험의 DB 보존 표식이 없으면 AWS 호출 전에 거부합니다."""
    environment, command_capture = fake_aws
    result = subprocess.run(
        [
            shutil.which("bash") or "bash",
            str(DEPLOY_SCRIPT),
            "--instance-id",
            "i-00000000000000001",
            "--secret-parameter",
            "/b7-1/e2e/environment",
            "--failure-injection",
            "after-start",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert "B7_1_E2E_PRESERVE_CHAT_MARKER" in result.stderr
    assert not command_capture.exists()


def test_ubuntu_deploy_installs_aws_cli_from_official_script():
    """Ubuntu 배포에서 저장소에 없는 awscli 패키지 대신 AWS 공식 설치기를 사용합니다."""
    deploy_source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    ec2_source = (PROJECT_ROOT / "scripts/ec2/deploy_ec2.sh").read_text(encoding="utf-8")

    assert "DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl unzip" in deploy_source
    assert "curl -fsSL https://awscli.amazonaws.com/v2/install.sh | bash -s -- --system" in deploy_source
    assert "apt-get install -y awscli" not in deploy_source
    assert "apt-get install -y awscli" not in ec2_source


def test_remote_command_pins_the_requested_revision(fake_aws):
    """원격 checkout 명령에 지정한 SHA와 브랜치 포함 검증을 전달합니다."""
    environment, command_capture = fake_aws
    environment["B7_1_E2E_PRESERVE_CHAT_MARKER"] = "e2e_preserve_123_1"
    environment["B7_1_E2E_READY_MARKER"] = "/run/b7-1-e2e-ready-123-1"
    revision = "a1b2c3d4e5f678901234567890abcdef12345678"
    result = subprocess.run(
        [
            shutil.which("bash") or "bash",
            str(DEPLOY_SCRIPT),
            "--instance-id",
            "i-00000000000000001",
            "--secret-parameter",
            "/b7-1/e2e/environment",
            "--branch",
            "develop",
            "--revision",
            revision,
            "--failure-injection",
            "after-start",
            "--require-e2e-test-instance",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    remote_command = base64.b64decode(command_capture.read_text(encoding="utf-8")).decode("utf-8")
    syntax_check = subprocess.run(
        [shutil.which("bash") or "bash", "-n"],
        input=remote_command,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert syntax_check.returncode == 0, syntax_check.stderr
    dirty_worktree_guard = 'status --porcelain'
    assert dirty_worktree_guard in remote_command
    assert 'worktree_status="$(git ' in remote_command
    assert 'status --porcelain)" || { echo' in remote_command
    assert remote_command.index(dirty_worktree_guard) < remote_command.index(f"reset --hard {revision}")
    deploy_source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "원격 저장소 작업 트리 상태를 확인하지 못했습니다." in deploy_source
    assert "원격 저장소 작업 트리에 변경이 있어 배포를 중단합니다." in deploy_source
    assert f"merge-base --is-ancestor {revision} origin/develop" in remote_command
    assert f"reset --hard {revision}" in remote_command
    assert "get-parameter --name /b7-1/e2e/environment --with-decryption" in remote_command
    assert "B7_1_E2E_FAILPOINT=after-start" in remote_command
    assert "B7_1_E2E_PRESERVE_CHAT_MARKER=e2e_preserve_123_1" in remote_command
    assert "B7_1_E2E_READY_MARKER=/run/b7-1-e2e-ready-123-1" in remote_command
    assert "[[ -f /etc/b7-1/e2e-test-instance" in remote_command
    assert "root:600" in remote_command
    assert 'install -o ubuntu -g ubuntu -m 600 "$env_backup"' in remote_command
    assert 'cmp -s -- "$env_backup"' in remote_command
    assert "ENV_ROLLBACK_SNAPSHOT_RETAINED=%s" in remote_command
    assert 'if [[ -n $env_backup ]]; then rm -f -- "$env_backup"; fi' not in remote_command
