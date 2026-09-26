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
