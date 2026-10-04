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
    parameters_capture = tmp_path / "ssm_parameters.txt"
    command_line_capture = tmp_path / "ssm_command_line.txt"
    delivery_timeout_capture = tmp_path / "ssm_delivery_timeout.txt"
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
        "    pathlib.Path(os.environ['E2E_SSM_PARAMETERS']).write_text(parameters)\n"
        "    command_line = parameters.partition('commands=')[2].partition(',executionTimeout=')[0]\n"
        "    pathlib.Path(os.environ['E2E_SSM_COMMAND_LINE']).write_text(command_line)\n"
        "    timeout = arguments[arguments.index('--timeout-seconds') + 1]\n"
        "    pathlib.Path(os.environ['E2E_SSM_DELIVERY_TIMEOUT']).write_text(timeout)\n"
        "    command = command_line.partition(' | base64 --decode')[0]\n"
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
    environment["E2E_SSM_PARAMETERS"] = str(parameters_capture)
    environment["E2E_SSM_COMMAND_LINE"] = str(command_line_capture)
    environment["E2E_SSM_DELIVERY_TIMEOUT"] = str(delivery_timeout_capture)
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


def test_deploy_logs_revision_for_the_root_owned_safe_directory():
    """root가 ubuntu 소유 체크아웃에서 배포 커밋을 기록할 때 Git 안전 경로를 지정합니다."""
    ec2_source = (PROJECT_ROOT / "scripts/ec2/deploy_ec2.sh").read_text(encoding="utf-8")

    assert 'git -c safe.directory="${PROJECT_DIR}" -C "${PROJECT_DIR}" rev-parse HEAD' in ec2_source


def test_cron_backup_script_is_executable_in_git():
    """Cron에서 직접 실행하는 백업 스크립트가 Git에도 실행 파일로 기록됩니다."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(PROJECT_ROOT),
            "ls-files",
            "--stage",
            "--",
            "scripts/ec2/backup_db.sh",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.split(maxsplit=1)[0] == "100755"


def test_remote_command_pins_the_requested_revision(tmp_path: Path, fake_aws):
    """원격 checkout 명령에 지정한 SHA와 브랜치 포함 검증을 전달합니다."""
    environment, command_capture = fake_aws
    environment["B7_1_E2E_PRESERVE_CHAT_MARKER"] = "e2e_preserve_123_1"
    environment["B7_1_E2E_READY_MARKER"] = "/run/b7-1-e2e-ready-123-1"
    environment["WAIT_SECONDS"] = "75"
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
    ssm_parameters = Path(environment["E2E_SSM_PARAMETERS"]).read_text(encoding="utf-8")
    assert "executionTimeout=735" in ssm_parameters
    ssm_command_line = Path(environment["E2E_SSM_COMMAND_LINE"]).read_text(encoding="utf-8")
    assert "| timeout --signal=TERM --kill-after=600s 75s bash" in ssm_command_line
    assert Path(environment["E2E_SSM_DELIVERY_TIMEOUT"]).read_text(encoding="utf-8") == "120"
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
    rollback_trap = (
        remote_command.partition("rollback_remote_state() {")[2]
        .partition("trap rollback_remote_state EXIT")[0]
    )
    assert 'deploy_pid="${!:-}"' in rollback_trap
    assert 'wait "$deploy_pid" || true' in rollback_trap
    assert rollback_trap.index('wait "$deploy_pid" || true') < rollback_trap.index(
        "git -c safe.directory="
    )
    rollback_function = (
        "rollback_remote_state() {"
        + remote_command.partition("rollback_remote_state() {")[2].partition("\n}\n")[0]
        + "\n}"
    )
    rollback_probe = "\n".join(
        [
            "set -u",
            "deploy_pid=''",
            "previous_revision=''",
            'env_temp="$TEST_ENV_TEMP"',
            "env_backup=''",
            "env_written=0",
            rollback_function,
            "set +e",
            "false",
            "rollback_remote_state",
        ]
    )
    rollback_environment = os.environ.copy()
    rollback_environment["TEST_ENV_TEMP"] = str(tmp_path / "not-created")
    rollback_result = subprocess.run(
        [shutil.which("bash") or "bash", "-c", rollback_probe],
        env=rollback_environment,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert rollback_result.returncode == 1
    assert "unbound variable" not in rollback_result.stderr
    deploy_launch = remote_command.index(
        "bash /home/ubuntu/app/B7-1/7-1/scripts/ec2/deploy_ec2.sh &"
    )
    assert remote_command.index("deploy_pid=$!", deploy_launch) > deploy_launch
    assert remote_command.index('wait "$deploy_pid"', deploy_launch) > deploy_launch
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


def test_timeout_waits_for_inner_rollback_before_outer_rollback(tmp_path: Path):
    """협조적 시간 제한에서 내부 롤백 완료 후 외부 롤백이 시작되는지 확인합니다."""
    bash_path = shutil.which("bash")
    timeout_path = shutil.which("timeout")
    if not bash_path or not timeout_path:
        pytest.skip("이 검증은 Linux Bash와 GNU timeout이 필요합니다.")

    rollback_log = tmp_path / "rollback-order.log"
    inner_script = tmp_path / "inner.sh"
    inner_script.write_text(
        "trap 'printf \"%s\\n\" inner-rollback-start >> \"$ROLLBACK_ORDER_LOG\"; "
        "sleep 0.2; printf \"%s\\n\" inner-rollback-done >> \"$ROLLBACK_ORDER_LOG\"' EXIT\n"
        "sleep 30\n",
        encoding="utf-8",
    )
    outer_script = (
        "set -Eeuo pipefail\n"
        "deploy_pid=''\n"
        "rollback_remote_state() {\n"
        "  local result=$?\n"
        "  trap - EXIT\n"
        "  set +e\n"
        "  if [[ -z ${deploy_pid:-} ]]; then deploy_pid=\"$!\"; fi\n"
        "  if [[ -n ${deploy_pid:-} ]]; then wait \"$deploy_pid\" || true; fi\n"
        "  printf '%s\\n' outer-rollback >> \"$ROLLBACK_ORDER_LOG\"\n"
        "  exit \"$result\"\n"
        "}\n"
        "trap rollback_remote_state EXIT\n"
        "bash \"$INNER_SCRIPT\" &\n"
        "deploy_pid=$!\n"
        "wait \"$deploy_pid\"\n"
    )
    environment = os.environ.copy()
    environment["ROLLBACK_ORDER_LOG"] = str(rollback_log)
    environment["INNER_SCRIPT"] = str(inner_script)
    result = subprocess.run(
        [timeout_path, "--signal=TERM", "--kill-after=2s", "0.2s", bash_path, "-c", outer_script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode in {124, 143}
    assert rollback_log.read_text(encoding="utf-8").splitlines() == [
        "inner-rollback-start",
        "inner-rollback-done",
        "outer-rollback",
    ]
