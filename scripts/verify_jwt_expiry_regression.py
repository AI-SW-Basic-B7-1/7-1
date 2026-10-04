"""만료 검증을 제거한 격리 사본에서 회귀 테스트가 실패하는지 확인합니다."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_NODE = "tests/test_chat_auth_integration.py::test_registered_users_expired_token_is_rejected_without_ai_call"
ORIGINAL_OPTIONS = 'options={"require": ["exp", "sub"]}'
MUTATED_OPTIONS = 'options={"require": ["sub"], "verify_exp": False}'


def main() -> int:
    """만료 검증 비활성화 변형이 실제 만료 토큰 테스트를 깨뜨리는지 확인합니다."""
    with tempfile.TemporaryDirectory(prefix="b7-1-jwt-exp-mutation-") as temporary_dir:
        isolated_root = Path(temporary_dir)
        shutil.copytree(PROJECT_ROOT / "app", isolated_root / "app")
        shutil.copytree(PROJECT_ROOT / "static", isolated_root / "static")
        shutil.copytree(PROJECT_ROOT / "tests", isolated_root / "tests")
        shutil.copy2(PROJECT_ROOT / "pytest.ini", isolated_root / "pytest.ini")

        auth_path = isolated_root / "app" / "auth.py"
        auth_source = auth_path.read_text(encoding="utf-8")
        if auth_source.count(ORIGINAL_OPTIONS) != 1:
            print("만료 검증 변형 위치가 코드와 일치하지 않습니다.", file=sys.stderr)
            return 1
        auth_path.write_text(
            auth_source.replace(ORIGINAL_OPTIONS, MUTATED_OPTIONS),
            encoding="utf-8",
        )
        base_temp = isolated_root / ".pytest-tmp"
        base_temp.mkdir()
        environment = os.environ.copy()
        environment["SECRET_KEY"] = "isolated-jwt-exp-mutation-test-secret"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                TEST_NODE,
                f"--basetemp={base_temp}",
            ],
            cwd=isolated_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        if result.returncode == 0 or "assert 200 == 401" not in output:
            print("만료 검증 비활성화 변형을 회귀 테스트가 검출하지 못했습니다.", file=sys.stderr)
            return 1

    print("만료 검증 비활성화 변형을 등록 사용자 E2E 테스트가 검출했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
