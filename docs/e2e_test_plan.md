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

## Windows·WSL 및 원격 브라우저 실행 상태

2026-10-04 확인 기준으로 저장소 기본 브랜치는 `develop`이며, 개발 통합 기준은 `fe44772cfbb40c8a507691936137b827a4a7bc17`입니다. PR #75의 검증 대상은 `feat/auth-ec2-ko`의 `04110dec409e9c40339a1e692863b1117d753241`입니다. PR #75는 열려 있고 팀원 승인 대기 상태입니다. 기존 GitHub CI의 Python·프런트엔드 및 Chromium 브라우저 작업은 통과했습니다.

WSL 테스트 가상환경에서 Playwright가 요구하는 Chromium Linux 패키지를 설치했습니다. 격리 SQLite와 AI 대역을 사용하는 로컬 Chromium 가입·로그인·채팅·이력 복원 테스트 1개가 통과했습니다. 비밀값이 없는 JUnit 보고서는 `logs/e2e/wsl-local-browser.xml`에 있습니다. 이 결과는 HTTPS 테스트 EC2, 실제 Gemini, DNS·인증서, 로그 회전이나 배포 롤백 검증을 의미하지 않습니다.

전용 테스트 EC2는 `ap-northeast-2`의 `i-011cd11330626e74c`이며, 배포 대상은 `https://ptrip-test.duckdns.org`입니다. GitHub `e2e` 환경에 배포 변수와 Parameter Store 이름이 등록돼 있습니다. 승인 전에는 GitHub Actions 대신 AWS CloudShell에서 제한된 SSM 배포 스크립트를 직접 실행해 실제 배포 검증을 진행합니다. 기존 운영 EC2는 배포 대상으로 사용하지 않습니다.

GitHub의 `workflow_dispatch`는 실제 기본 브랜치에 워크플로가 있어야 수동 실행할 수 있습니다. PR #76은 `develop` 기준으로 워크플로 파일 하나만 추가하는 PR로 수정합니다. 기본 브랜치에 등록되기 전까지 해당 Actions 실행 경로는 대기합니다. 승인 없이 수행하는 SSM 검증과 Actions/OIDC 검증 결과는 별도로 기록합니다.

### 실행 단계와 통과 조건

| 단계 | 수행 내용 | 통과 조건 |
| --- | --- | --- |
| 1. 로컬 검증 고정 | 기준 브랜치·전체 SHA, 기존 Python·Node·변형 대조 테스트 결과, WSL Chromium 결과를 실행 환경별로 기록합니다. | 배포 대상 코드의 SHA와 테스트 보고서가 대응됩니다. |
| 2. PR 범위 정정 | PR #76을 `develop` 기준 단일 워크플로 추가로 재구성합니다. PR #75에는 이번 WSL Chromium 통과와 미실행 EC2 검증을 기록합니다. | PR #76 파일 범위가 `.github/workflows/deploy-test-ec2.yml` 하나이고 #75의 전체 이슈 링크가 유지됩니다. |
| 3. AWS 사전 검사 | CloudShell에서 계정·리전, EC2 상태, SSM Online, 전용 인스턴스 역할·파라미터 권한, 테스트 표식, DNS와 보안 그룹을 확인합니다. SecureString 내용은 출력하지 않습니다. | 대상이 테스트 인스턴스이고 SSM·파라미터·표식이 준비되며 HTTPS 경로가 대상 IP를 가리킵니다. |
| 4. 고정 SHA 직접 배포 | CloudShell에서 `scripts/ec2/run_ec2_deploy.sh`를 실행해 테스트 표식과 브랜치 포함 여부를 확인하고 기록한 전체 SHA를 배포합니다. | SSM 배포와 원격 단위 테스트가 성공하고 systemd·Nginx가 준비됩니다. |
| 5. 실제 HTTPS 브라우저 검증 | 테스트 도메인에서 인증서, HTTP 전환, 정적 파일, 가입·로그인·Gemini 채팅·이력 복원, 내부 파일 차단을 확인합니다. | 브라우저 응답과 저장 이력이 일치하고 서비스 요청 ID가 서버 로그와 연결됩니다. |
| 6. 복구와 로그 검증 | 테스트 인스턴스 표식을 재확인하고 기동 전·후 실패를 각각 주입합니다. 기동 후 질문은 DB 커밋을 확인한 다음 실패를 주입합니다. SQLite 무결성, 이전 코드·서비스 설정 복원, 로그 회전 전후 요청 추적을 검사합니다. | 두 실패 지점의 롤백 완료를 확인하고, 기동 후 저장 기록이 남으며, 서비스·Cron·로그 설정과 DB가 검증됩니다. |
| 7. 전체 코드 재검토 | 최종 코드·워크플로 변경을 솔(high) 서브에이전트가 프런트/API·인증·AI·DB·IAM·배포 경로 전체 관점으로 재검토합니다. 지적 사항은 수정 후 영향받은 검증을 반복합니다. | P0/P1 지적이 없고 남은 운영 제한이 결과에 명시됩니다. |
| 8. 증거 보관 및 중지 | SHA, SSM 실행 ID, 비밀값 없는 테스트 결과를 정리하고 테스트 EC2를 중지합니다. | AWS 콘솔에서 테스트 인스턴스 상태가 `stopped`입니다. 기존 인스턴스는 건드리지 않습니다. |
| 9. 승인 후 실행 | PR #76 또는 #75가 기본 브랜치에 병합되면 Actions `workflow_dispatch`와 OIDC 인수를 검증합니다. PR #75 병합 뒤에는 최종 `develop` SHA를 다시 배포·검증하고 인스턴스를 다시 중지합니다. | GitHub Actions, OIDC, 병합 후 최종 SHA까지 확인됩니다. |

배포 명령의 브랜치와 SHA는 실행 직전에 원격에서 다시 확인합니다. 실패한 단계의 SSM 상태와 출력으로 원인을 확인한 뒤 영향받은 단계만 재실행합니다. 테스트 보고서와 PR에는 계정 암호, JWT, SecureString, `.env`, DB 파일 또는 실제 Gemini 답변 전문을 포함하지 않습니다. 인스턴스를 다시 시작한 뒤 공인 IP가 달라지면 DuckDNS A 레코드를 갱신하고 HTTPS를 재확인합니다.

GitHub 수동 실행 조건은 [GitHub 수동 실행 문서](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow), AWS OIDC 설정은 [GitHub AWS OIDC 안내](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)를 따릅니다.
