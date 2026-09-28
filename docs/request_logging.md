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

```bash
venv/bin/python -m pytest tests/test_request_logging.py tests/test_chat_router.py -q
tail -f logs/app.log
```

운영체제별 로그 검증 스크립트 정비는 이슈 #17의 별도 작업으로 남습니다.

## EC2 배포와 로그 설정

`scripts/ec2/deploy_ec2.sh`는 기본 사이트와 서비스 설정을 작성한 뒤
`configure_nginx_logs.sh --prepare`로 로그 설정을 추가합니다. 이후 서비스를
재시작하고 `--verify`로 응답 헤더, 앱·Nginx 요청 ID 연결, 쿼리·Referer 비기록,
로그 경로 차단 및 프로세스의 표준 출력·오류 경로를 검증합니다.
사이트 경로와 서비스 이름은 배포 설정에서 함께 전달하므로 재배포 시에도 유지됩니다.

설정 구간 이후 배포가 실패하면 이전 사이트·서비스·로그 드롭인 설정과 사이트 링크를
복원하고, 서비스 재시작 단계에 도달했다면 이전 실행 여부에 맞춰 재시작하거나 중지합니다.
이는 앱 코드·DB·패키지·자동 시작 등록·백업 예약까지 되돌리는 전체 배포 롤백은 아닙니다.

이미 실행 중인 서버에서는 인자 없이 로그 설정 스크립트를 단독 실행할 수도 있습니다.
`--prepare`는 서비스 재시작과 실행 검증을 하지 않으므로 단독 적용 완료로 간주하지 않습니다.

`app.log`의 기존 Python 회전 정책은 유지합니다. `nginx_access.log`,
`nginx_error.log`, `server.log`의 자동 회전 정책 설치는 아직 별도 후속 작업입니다.
이번 변경에는 UFW 설정이 포함되지 않습니다.
