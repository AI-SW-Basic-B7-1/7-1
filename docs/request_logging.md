# HTTP 요청 로그

FastAPI에 도착한 모든 HTTP 요청은 콘솔과 `logs/app.log`에 기록합니다.
GET, POST, OPTIONS, 정적 파일 및 헬스체크도 포함합니다. Nginx가 직접
처리한 요청이나 브라우저 캐시에서 처리된 요청은 이 로그에 포함되지 않습니다.

## 추적 번호

서버가 요청마다 전체 UUID를 생성하여 `request.state.request_id`에 보관합니다.
클라이언트가 보낸 추적 번호는 사용하지 않습니다. 응답의 `X-Request-ID`와
HTTP·AI·DB 로그의 번호가 같습니다. 로그 필터는 비동기 요청별 문맥에서
번호를 읽어 기존 이벤트에도 추가합니다. 충돌 위험 때문에 이전 6자리 표시는
전체 UUID로 대체합니다. 교차 출처 정상 응답에서는 CORS 노출 헤더로 제공합니다.

## 형식과 시간

```text
2026-09-23 20:00:00+0900 INFO http_request_started method=POST path=/api/chat request_id=UUID
2026-09-23 20:00:01+0900 INFO db_save_success user_id=3 chat_id=8 request_id=UUID
2026-09-23 20:00:01+0900 INFO http_request_completed method=POST path=/api/chat status_code=200 duration_ms=1000 request_id=UUID
```

- 로그 시각은 서버 프로세스의 로컬 시간대와 UTC 오프셋을 사용합니다.
- `duration_ms`는 미들웨어 진입부터 하위 ASGI 앱 반환까지입니다. 응답 본문
  전달과 등록된 백그라운드 작업이 포함될 수 있으며 브라우저 수신 시간은 아닙니다.
- `latency_ms`는 기존 AI 호출 함수 실행 시간입니다.
- 정상 구성된 4xx·5xx 응답도 `http_request_completed`로 기록합니다.
- 미처리 예외는 `http_request_failed`와 스택 트레이스로 기록하고 공통
  예외 처리기의 중복 기록은 생략합니다. 응답 시작 전이면 상태 코드는 500이며,
  이미 응답이 시작된 뒤 오류가 발생하면 실제 전송된 상태 코드를 유지합니다.
- 스트리밍·백그라운드 작업 오류가 발생했을 때 이미 전송한 응답을 교체할 수는 없습니다.

## 보안 및 검증

공통 HTTP 로그는 요청 본문, 인증 헤더, 쿠키, 쿼리 문자열을 수집하지 않습니다.
예외 메시지와 URL 경로에는 민감정보가 들어가지 않도록 작성해야 합니다.
스택 트레이스에는 예외 메시지가 포함되므로 로그 파일 접근 권한도 제한해야 합니다.
Uvicorn·Nginx 접근 로그는 별도 설정이며 이 정책으로 자동 변경되지 않습니다.

애플리케이션 로거는 콘솔·파일 출력 직전에 설정된 `SECRET_KEY`,
`GEMINI_API_KEY`, Bearer 토큰과 이름이 명시된 비밀번호·토큰 값을
`[REDACTED]`로 치환합니다. 예외 체인과 스택 트레이스에도 적용됩니다.
임의의 질문·답변이나 이름 없이 포함된 민감정보까지 탐지하는 기능은 아닙니다.
Uvicorn 자체의 오류 출력과 Nginx 로그에는 이 포맷터가 적용되지 않습니다.
따라서 모든 서버 로그의 비밀값 비노출을 보장하지 않으며, 배포 검증이 필요합니다.

DB 초기화 실패는 `database_initialization_failed`와 스택 트레이스로 기록하고
예외를 다시 전달해 애플리케이션 시작을 중단합니다. 이 이벤트는 HTTP 요청이
아니므로 요청 ID가 없습니다.

```bash
venv/bin/python -m pytest tests/test_request_logging.py tests/test_chat_router.py -q
tail -f logs/app.log
```

운영체제별 로그 검증 스크립트 정비는 이슈 #17의 별도 작업으로 남습니다.

<<<<<<< HEAD
## EC2 배포와 로그 설정

`scripts/ec2/deploy_ec2.sh`는 기본 사이트와 서비스 설정을 작성한 뒤
`configure_nginx_logs.sh --prepare`로 로그 설정을 추가하고
`configure_log_rotation.sh`로 회전 정책을 설치합니다. 이후 서비스를
재시작하고 `--verify`로 응답 헤더, 앱·Nginx 요청 ID 연결, 쿼리·Referer 비기록,
로그 경로 차단 및 프로세스의 표준 출력·오류 경로를 검증합니다.
사이트 경로와 서비스 이름은 배포 설정에서 함께 전달하므로 재배포 시에도 유지됩니다.

설정 구간 이후 배포가 실패하면 이전 사이트·서비스·로그 드롭인 설정과 사이트 링크를
복원합니다. 로그 회전 정책과 예약 파일도 복원하며, 서비스 재시작 단계에 도달했다면
이전 실행 여부에 맞춰 재시작하거나 중지합니다.
이는 앱 코드·DB·패키지·자동 시작 등록·백업 예약까지 되돌리는 전체 배포 롤백은 아닙니다.

이미 실행 중인 서버에서는 인자 없이 로그 설정 스크립트를 단독 실행할 수도 있습니다.
`--prepare`는 서비스 재시작과 실행 검증을 하지 않으므로 단독 적용 완료로 간주하지 않습니다.

이번 변경에는 UFW 설정이 포함되지 않습니다.

## 운영 로그 회전

`scripts/ec2/configure_log_rotation.sh`는 Nginx 접근·오류 로그와 `server.log`만
관리합니다. `app.log`는 기존 Python 회전(5MiB, 백업 3개)을 유지합니다.

- 매시간 17분에 검사하며 하루가 지났거나 5MiB를 초과한 비어 있지 않은 파일을 회전합니다.
- 백업은 파일별 7개입니다. 7일 보관을 보장하는 정책은 아닙니다.
- 최근 백업 `.1`은 압축을 유예하고 이전 백업은 `.2.gz`부터 압축합니다.
- 검사 사이에는 5MiB를 초과할 수 있으므로 엄격한 디스크 사용량 상한이 아닙니다.
- Nginx는 파일 이름 변경 후 마스터에 USR1 신호를 보내 새 파일을 열게 합니다.
- `server.log`는 `copytruncate`로 기존 파일을 유지하므로 앱 재시작이 필요 없습니다.
  단, 복사와 비우기 사이 기록이 유실될 수 있어 무손실 감사 로그 용도로는 적합하지 않습니다.
- 새 Nginx 로그 권한은 0640이며 서버 로그는 기존 권한을 유지합니다.

정책은 `/etc` 아래 `b7-1/logrotate.conf`, 예약은 `cron.d/b7-1-logrotate`에
설치합니다. 상태는 `/var/lib` 아래 `b7-1-logrotate/status`로 분리합니다.
시스템의 기본 `logrotate.d`에 중복 등록하지 않습니다. 기존에 수동으로 등록한
동일 파일 대상 정책이 있다면 운영자가 중복을 제거해야 합니다.
설치 과정은 디버그 검사만 수행하며 운영 로그를 강제로 회전하지 않습니다.
설치 실패 시 정책·예약 파일을 복원합니다. cron 활성화와 회전 상태 이력은 유지합니다.

기존 서버에는 `logrotate`와 `cron` 패키지를 준비한 뒤 별도로 설치할 수 있습니다.

```bash
sudo apt-get install -y logrotate cron
sudo bash scripts/ec2/configure_log_rotation.sh
venv/bin/python -m pytest tests/test_ec2_logging_config.py -q
```

실제 회전 도구 테스트는 `logrotate`가 없으면 건너뜁니다. 설치된 환경에서는 임시
로그만 대상으로 강제 회전하여 압축·백업 7개·열린 서버 로그 핸들의 기록 지속을 확인합니다.
이 테스트의 Nginx 신호 수신자는 대역이므로 EC2에서 실제 회전 후 새 요청이
현재 `nginx_access.log`에 남는지, `server.log` 기록이 계속되는지는 추가 확인해야 합니다.

참고: [Nginx 로그 재열기](https://nginx.org/en/docs/control.html),
[logrotate 공식 매뉴얼](https://github.com/logrotate/logrotate/blob/main/logrotate.8.in).
=======
## EC2 점검

프로젝트 루트에서 다음 명령을 실행합니다. 서비스 설정 변경·재시작·고의 장애는
발생시키지 않으며, 정상 헬스체크 요청 한 번과 로그 읽기만 수행합니다.

```bash
sudo bash scripts/ec2/check_error_logging.sh
```

스크립트는 활성 서비스, 실제 표준 출력 설정, 헬스체크 응답 ID와 `app.log`의
완료 이벤트 연결을 확인합니다. `server.log`, `nginx_access.log`는 존재 여부만
확인하므로 통과 메시지가 모든 장애 로그 검증 완료를 의미하지는 않습니다.
`PROJECT_DIR`, `LOG_DIR`, `BASE_URL`, `SERVICE_NAME`으로 환경을 지정할 수 있습니다.

현재 저장소의 `deploy_ec2.sh`는 표준 출력을 journal로 설정합니다.
서버에 별도 적용한 설정이 있다면 스크립트가 출력한 `StandardOutput`과
`StandardError`를 기준으로 판단합니다. 로그가 journal에만 있다고 장애는 아닙니다.

실제 장애가 재발하면 발생 시각과 `X-Request-ID`를 확보한 뒤 제한된 터미널에서
`logs/app.log`와 회전 로그를 확인합니다. 같은 요청의 오류 이벤트 바로 다음에
호출 경로·예외 종류가 있는지 확인하고, 민감값은 공유 전에 삭제합니다.
서비스 출력이 journal이면 `sudo journalctl -u chatbot.service -n 100 --no-pager`로,
파일이면 `logs/server.log`로 확인합니다. 운영 서버에서 DB 잠금이나 권한 변경으로
고의 장애를 만들지 않습니다.
>>>>>>> develop
