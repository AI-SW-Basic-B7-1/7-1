# 전체 E2E 및 배포 검증

이 문서는 이슈 #74, #26, #55를 현재 `develop` 전체와 PR #75에 우선 적용해 브라우저, API, SQLite, 표준 로그, 테스트 EC2 배포까지 검증하는 방법을 정의합니다. PR #70, #71, #73의 기능 검증은 각 PR이 병합되는 순서대로 동일한 전체 회귀 파이프라인에 추가합니다.

## 실행 계층

| 명령 또는 워크플로 | 검증 범위 | 외부 서비스 |
| --- | --- | --- |
| `python -m pytest -q tests --ignore=tests/e2e` | Python 단위·API·SQLite·인증·배포 구성 | 없음 |
| `node --test tests/frontend/*.test.mjs` | 프론트 계약·렌더링·오류·키보드 | 없음 |
| `python -m pytest -q tests/e2e --browser chromium` | 실제 브라우저 가입·로그인·채팅·기록 복원, 임시 SQLite | 격리 AI 대역만 사용 |
| `E2E 품질 검사` | Python·Node 단위/통합 테스트, 만료 검증 변형 대조, 셸 문법 | 없음 |
| `테스트 EC2 배포 및 브라우저 E2E` | 브랜치 소속 고정 SHA 배포, 실제 브라우저, 배포 실패 복구, HTTPS 로그 회전 전후 추적 | 별도 테스트 EC2·제한 AWS OIDC 역할 |

배포 스크립트의 기본 pytest는 브라우저 의존성이나 AI 네트워크에 기대지 않습니다. 브라우저 E2E는 별도의 의존성 파일과 명령으로 실행합니다. 원격 브라우저 검증은 실제 Gemini 답변 문구를 고정하지 않고 성공 답변이 화면과 저장 이력에 나타나는지 확인합니다.

Windows에서 pytest 임시 디렉터리 권한 오류가 발생하면 프로젝트 안에 새 임시 경로를 지정합니다. 예: `python -m pytest -q tests --ignore=tests/e2e --basetemp=.pytest-tmp-local`.

## 인증 및 기능 통과 기준

- 이슈 #55: 격리 SQLite에 등록한 계정의 유효 토큰은 채팅에 성공합니다. 같은 계정의 만료 토큰은 401이며 AI 대역은 호출되지 않고 새 기록도 저장되지 않습니다. 유효 토큰 대조 요청을 먼저 성공시켜 사용자 미존재로 인한 오탐을 막습니다.
- `python scripts/verify_jwt_expiry_regression.py`는 `app/auth.py`에서 만료 검증을 제거한 격리 사본으로 등록 계정의 만료 토큰 테스트를 실행합니다. 테스트가 401 대신 200을 받아 실패하는지 확인하며 현재 작업 파일은 수정하지 않습니다.
- 이슈 #74: 기본·예시 `SECRET_KEY`로 실제 서버 기동이 실패하고 무작위 키에서는 기동 및 가입이 성공합니다. 가입·로그인의 ASCII 72/73바이트 및 한글 바이트 경계는 유효/422로 구분합니다. bcrypt 처리 중 보조 health 요청이 응답해야 합니다.
- 이슈 #26: 브라우저 가입·로그인·채팅·화면 응답 뒤 재접속 및 재로그인으로 같은 대화방·기록을 복원합니다. 로그인 A/B 간 대화와 문맥은 격리됩니다.
- 질문 공백·501자, 만료 토큰, AI 502/504, SQLite 읽기·쓰기 실패를 각각 검증하고 이후 정상 요청이 다시 처리되는지 확인합니다. 실패 경로에 사용자 AI 문답을 일부 기록하지 않습니다.
- CI 브라우저 대역은 결정적 답변을 반환하고, 실제 답변 문구를 하드코딩하지 않은 채 API 응답과 점진 표시 완료 화면, 재로그인 뒤 저장 기록을 정확히 비교합니다. 테스트 EC2는 실제 Gemini를 호출합니다.

## 배포, 저장, 로그 및 복구 기준

- 수동 배포 실행은 `workflow_dispatch` 입력에 브랜치와 전체 커밋 SHA를 모두 지정합니다. 입력 SHA가 브랜치의 조상인지 먼저 확인하고, 원격 스크립트도 브랜치에 해당 SHA가 있는지 확인한 뒤 그 커밋으로 정확히 재설정합니다.
- GitHub `e2e` 환경에는 `E2E_AWS_REGION`, `E2E_AWS_ROLE_ARN`, `E2E_EC2_INSTANCE_ID`, `E2E_SECRET_PARAMETER`, `E2E_BASE_URL` 저장소 변수가 필요합니다. AWS OIDC 역할의 신뢰 범위는 저장소와 `e2e` 환경으로 제한합니다. 인스턴스 역할의 Parameter Store 권한도 테스트 경로의 SecureString으로 한정합니다.
- 테스트 배포는 사전 설정한 `/etc/b7-1/e2e-test-instance` 표식을 root 소유·권한 600으로 확인하고, 표식이 없으면 배포 전에 중단합니다. 실패 주입도 이 표식이 있는 테스트 EC2에서만 `before-start` 및 `after-start` 복구 시험을 실행합니다.
- 테스트 URL은 HTTPS여야 합니다. HTTP→HTTPS 전환, 유효 인증서, `/` 및 `/static/` 자원, API 연결, SQLite·환경파일·내부 로그 직접 다운로드 차단, 외부 FastAPI 포트 차단을 확인합니다.
- 브라우저 질문이 같은 응답으로 화면과 `GET /api/me/chats`에 저장되어야 합니다. SQLite는 격리 테스트 EC2에서만 검사하며 무결성, `DATABASE_URL`, 백업 경로 일치와 복원 후 새 요청을 확인합니다.
- 브라우저 채팅 응답의 `X-Request-ID`를 SSM 검증기에 전달해 같은 사용자·요청에 `request_received`, `ai_call_start`, `ai_call_success`, `db_save_success`가 연결되는지 확인합니다. 만료·AI·DB 실패에는 실패 이벤트와 응답 코드가 연결되고 인증 실패에서는 AI 및 저장 성공 이벤트가 없어야 합니다.
- 기동 전 실패는 별도 workflow 단계에서 이전 서비스의 로그인과 기존 대화 저장 기록을 확인한 뒤에만 기동 후 시험을 시작합니다. 실패 주입 출력에는 주입 도달과 코드 SHA, DB 무결성, 서비스/Cron 상태, systemd·Cron·로그 설정 파일 복원이 모두 확인됐을 때의 완료 표식이 각각 있어야 합니다.
- 기동 후 실패는 workflow가 새 서비스의 준비 표식을 기다린 뒤 브라우저로 고유 질문을 보내고 로그아웃·재로그인해 응답 복원을 확인합니다. workflow가 완료 확인 신호를 전달하고, 배포 스크립트가 같은 질문이 SQLite에 커밋된 것을 확인한 뒤에만 실패를 주입합니다. 롤백 뒤에도 그 질문이 남아 있고 기존 서비스·systemd·Cron·로그 설정이 복원됐는지 확인합니다.
- `scripts/ec2/verify_e2e_log_rotation.sh`는 테스트 EC2 표식을 확인한 뒤 고유 probe 요청을 보내고, 프로젝트 `logs/app.log`와 Nginx 로그에서 회전 전후의 요청 ID 연결을 확인합니다. 회전된 로그와 활성 로그 모두에서 쿼리 probe가 보이지 않아야 합니다. 실제 회전 설정 파일은 배포 코드가 설치한 `/etc/logrotate.d/b7-1`을 검사합니다.

## 결과와 완료 증거

각 실행에는 환경, 커밋 SHA, 시작 시각, 시나리오, 기대·실제 결과, 통과·실패와 비밀값이 없는 테스트 보고서를 남깁니다. JWT, 비밀번호, `.env`, DB 파일, 실제 Gemini 답변 전문은 GitHub 로그·아티팩트에 저장하지 않습니다.

이슈 #55는 등록 사용자 대조와 만료 검증 변형 실패까지, #74는 인증·HTTPS·비밀정보·DB와 systemd/Cron 복구까지, #26은 전체 테스트·리뷰·병합 후 최종 SHA의 테스트 EC2 브라우저·로그 회전 검증까지 완료하면 닫습니다.

## Windows 및 컴퓨터 유즈를 통한 상호작용 실행 계획

2026-10-04 사전 확인에서 현재 브랜치는 `feat/auth-ec2-ko`, HEAD는 `eed5f4e6adb915a285639244ffd597a02d46e512`이며 E2E 구현은 미커밋 변경입니다. Ubuntu WSL2와 기존 Linux 테스트 가상환경이 확인됐고 Python 3.14.4, Bash, OpenSSL, Git, pytest, pytest-asyncio를 사용할 수 있습니다. WSL에는 Node와 Playwright가 없습니다. 기존 Windows 환경의 Node와 Python 3.12 가상환경을 함께 사용합니다. 실행 직전에 이 상태와 원격 ref를 다시 확인합니다.

현재 컴퓨터 유즈의 브라우저 연결에는 Codex 내장 브라우저가 보입니다. Chrome 또는 Edge 사용을 선택하면 해당 브라우저를 사용할 수 있는 연결을 먼저 확인합니다. 계획 단계에서는 테스트 실행, 의존성 설치, 커밋·푸시·PR·병합, AWS 설정 변경과 배포를 수행하지 않습니다.

### 실행 순서와 통과 조건

| 단계 | 수행 내용 | 담당 및 상호작용 | 다음 단계로 넘어가는 조건 |
| --- | --- | --- | --- |
| 1. 로컬 상태 고정 | 변경 파일과 기준 SHA를 확인하고 기존 WSL 가상환경의 의존성을 점검합니다. 심볼릭 링크 등 POSIX 테스트의 임시 파일은 WSL의 Linux 임시 디렉터리에 둡니다. | 에이전트가 터미널 도구로 확인합니다. WSL 사용자 접근이 차단되면 호스트 사용자 권한으로 같은 명령을 실행합니다. | 필요한 패키지와 Bash/OpenSSL이 정상이고 소스 변경 범위가 확인됩니다. |
| 2. 건너뛴 테스트 실행 | `tests/test_ec2_deploy_revision.py`, `tests/test_ec2_e2e_log_rotation.py`, `tests/test_ec2_logging_config.py`를 WSL에서 실행합니다. 이후 Python 전체 단위·통합 테스트와 만료 검증 변형 대조를 같은 환경에서 실행하고 Node 테스트는 Windows에서 실행합니다. | 에이전트가 명령과 결과를 보여 줍니다. 실패 원인을 해결한 뒤 영향받은 검증을 다시 실행합니다. | 기존에 건너뛴 Bash/POSIX 테스트가 모두 실제로 실행되고 실패·건너뜀이 없습니다. 전체 Python·Node·변형 대조도 통과합니다. |
| 3. 로컬 브라우저 E2E | Windows의 공유 Python 가상환경에 `requirements-e2e.txt`와 Chromium을 준비하고 `tests/e2e`를 실행합니다. 자식 테스트 프로세스에서 원격 `E2E_*` 설정을 제거해 임시 SQLite와 AI 대역을 사용합니다. | 필요한 설치 항목을 먼저 알리고 에이전트가 터미널 도구로 준비·실행합니다. | 실제 Chromium에서 가입·로그인·채팅 화면·재로그인 후 같은 저장 기록 복원을 확인합니다. |
| 4. 원격 코드와 수동 실행 등록 | 검증한 구현을 원격에 반영할 커밋/PR 범위를 정하고 실제 테스트 대상 브랜치와 전체 SHA를 기록합니다. GitHub 기본 브랜치와 기존 배포 워크플로를 확인합니다. 수동 워크플로가 기본 브랜치에 없으면 등록에 필요한 변경을 PR로 반영합니다. 기능 코드 통합과 기본 브랜치의 워크플로 등록 범위는 각각 검토합니다. | 원격 반영에 앞서 변경 파일·커밋·PR 대상을 사용자에게 보여 줍니다. `main` 변경은 저장소 규칙에 따라 PR로 진행합니다. | 기본 브랜치에서 수동 워크플로가 등록되고, 배포 대상 SHA에 스크립트·테스트·의존성 파일이 모두 존재하며 대상 브랜치에 속합니다. |
| 5. GitHub/AWS 준비 | 브라우저에서 저장소의 Actions/환경 설정, AWS의 테스트 EC2·SSM·IAM·Parameter Store·DNS를 확인합니다. 필요한 설정값은 아래 표를 사용합니다. | 에이전트가 화면을 읽고 설정 내용과 다음 동작을 설명합니다. 사용자가 로그인/MFA와 비밀값 입력을 수행합니다. IAM 권한 생성·확대는 정확한 정책을 검토한 뒤 적용합니다. 새 EC2가 필요하면 리소스·비용 범위·사용 종료 시점을 먼저 정합니다. | 전용 테스트 인스턴스, SSM Online, 테스트용 설정, GitHub OIDC와 HTTPS 도메인이 준비됩니다. |
| 6. 화면에서 수동 실행 | GitHub Actions의 `테스트 EC2 배포 및 브라우저 E2E`에서 `Run workflow`를 엽니다. 워크플로 정의를 사용할 브랜치와 배포 입력 `branch`/`revision`을 구별해 확인하고 실행합니다. | 에이전트가 컴퓨터 유즈로 화면을 조작하고 사용자가 목표 인스턴스·도메인·전체 SHA를 함께 확인합니다. 단계별 결과는 새 화면 상태에서 읽습니다. | 고정 SHA 배포, HTTPS 브라우저/실 Gemini, 기동 전 롤백, 기동 후 새 DB 기록 보존, 롤백 후 재로그인·기록 복원, 채팅 이벤트/강제 로그 회전 단계가 모두 통과합니다. |
| 7. 실제 서비스 화면 및 결과 확인 | 테스트 HTTPS 사이트에서 직접 로그인·질문·응답·기록 복원을 확인하고 Actions 실행 URL, 실제 배포 SHA, 비밀값 없는 보고서와 로그 검증 결과를 정리합니다. 코드 수정이 발생했다면 Sol High에게 최신 전체 변경을 다시 검토시킵니다. | 사용자가 실제 화면을 함께 확인하고 에이전트가 결과를 정리합니다. | 로컬 WSL/Windows 결과, CI 결과, 실제 EC2 결과가 각각 확인되고 각 이슈의 완료 기준과 대응됩니다. |

WSL에서 먼저 실행할 명령은 저장소 루트를 기준으로 다음과 같습니다. `TEST_PYTHON`은 확인된 저장소 밖 Linux 가상환경의 Python 실행 파일로 설정합니다.

```bash
"$TEST_PYTHON" -m pytest -q tests/test_ec2_deploy_revision.py tests/test_ec2_e2e_log_rotation.py tests/test_ec2_logging_config.py --basetemp="$(mktemp -d)"
"$TEST_PYTHON" -m pytest -q tests --ignore=tests/e2e --basetemp="$(mktemp -d)"
"$TEST_PYTHON" scripts/verify_jwt_expiry_regression.py
```

현재 WSL의 Python 3.14 검증 결과는 GitHub CI의 Python 3.12 및 실제 EC2 환경 결과와 각각 기록합니다. WSL에 Node를 추가할 필요 없이 기존 Windows Node로 프론트엔드 테스트를 실행합니다. Windows에 Bash 경로만 추가하거나 심볼릭 링크를 위한 시스템 보안 설정을 변경하는 방식은 사용하지 않습니다.

### 준비할 값과 사용자 참여

| 항목 | 확인하거나 입력할 내용 | 처리 방식 |
| --- | --- | --- |
| 브라우저 | Codex 내장 브라우저 또는 연결된 Chrome/Edge | 실제 연결 목록에서 선택한 브라우저를 확인합니다. |
| GitHub 계정 권한 | `AI-SW-Basic-B7-1/7-1` 저장소의 Actions 실행 권한, PR 작업 권한, 필요한 환경 설정 권한 | 로그인/MFA는 사용자가 직접 진행하고 기존 권한을 먼저 확인합니다. |
| 테스트 EC2 | 리전, 인스턴스 ID, 실제 OS, 전용 테스트 용도, SSM 연결 상태 | 기존 인스턴스의 용도를 확인한 후 선택합니다. 미준비라면 새 리소스 계획을 확정합니다. |
| HTTPS 주소 | 테스트 도메인, DNS와 EC2 연결, 인증서, 80/443 및 외부 8000 접근 제한 | 화면 상태와 실제 네트워크 응답으로 확인합니다. |
| GitHub `e2e` 변수 | `E2E_AWS_REGION`, `E2E_AWS_ROLE_ARN`, `E2E_EC2_INSTANCE_ID`, `E2E_SECRET_PARAMETER`, `E2E_BASE_URL` | GitHub 환경 화면에서 값과 대상을 확인합니다. |
| AWS OIDC 역할 | 저장소와 `e2e` 환경에 맞는 실제 subject 조건, 테스트 인스턴스에 필요한 SSM 권한 | 기존/불변 ID subject 형식을 확인한 뒤 정책을 준비합니다. 토큰 자체는 출력하지 않습니다. |
| EC2 인스턴스 역할/환경 | 테스트 경로 SecureString 읽기 권한, 실제 Gemini 키·강한 JWT 키·DB 경로 등 앱 설정 | 비밀값은 사용자가 AWS 화면에 직접 입력합니다. 채팅·Git·보고서에는 키나 `.env` 전문을 넣지 않습니다. |
| 테스트 인스턴스 표식 | 배포 스크립트가 검사하는 테스트 EC2 표시 파일의 root 소유·600 권한 | 전용 테스트 인스턴스임을 확인한 후 준비하고 실패 주입 전 다시 검사합니다. |

한 단계에서 실패하면 해당 실패의 Actions/SSM 상태와 오류를 확인하고 후속 배포 단계를 보류합니다. 원인을 확인하지 않은 채 반복 실행하지 않습니다. 롤백 실패 표식이 나타나면 보존된 스냅샷과 실제 서비스 응답을 먼저 확인합니다. 테스트 데이터 정리와 인스턴스 중지·삭제는 대상 및 필요 증거를 정한 후 별도 단계로 진행합니다.

GitHub UI의 수동 실행은 워크플로 파일이 기본 브랜치에 있어야 하며, AWS OIDC 조건은 저장소의 현재 subject 형식과 환경 이름에 맞아야 합니다. 근거: [GitHub 수동 실행 문서](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow), [AWS OIDC 설정 문서](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).
