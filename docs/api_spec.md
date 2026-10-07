# AI Assistant REST API 명세

> 구현 대조: 2026-09-23, `develop`의 `755e7e2`.
> Base URL: `/api`. 로컬 [Swagger UI](http://127.0.0.1:8000/docs), [ReDoc](http://127.0.0.1:8000/redoc).
> 근거: [schemas.py](../app/schemas.py), [인증 라우터](../app/routers/auth_router.py), [채팅 라우터](../app/routers/chat_router.py), [예외 처리](../app/exception_handlers.py), [DB](../app/database.py).

## 1. 공통 계약

요청 본문은 JSON(`Content-Type: application/json`), 성공/오류 응답도 JSON입니다. 보호 API에는 `Authorization: Bearer <access_token>`을 보냅니다. 서버는 JWT 검증 뒤 DB 사용자를 조회하며, 클라이언트가 보낸 user_id를 사용자 식별 근거로 쓰지 않습니다.

앱 오류의 공통 형식은 `{"detail":"한국어 문자열"}`입니다. 422는 아이디·비밀번호·질문·대화방 ID의 알려진 검증 오류를 안전한 한국어 문구로 반환합니다. 그 밖의 오류는 `요청 데이터 형식이 올바르지 않습니다.`로 처리하며 Pydantic 기본 오류 배열이나 입력값은 반환하지 않습니다. 프록시의 HTML 오류는 앱 계약 밖이므로 클라이언트가 안전한 일반 문구로 처리합니다.

대화 이력의 `created_at`은 Pydantic이 변환한 `YYYY-MM-DDTHH:MM:SS` 형식입니다. 현재 DB 기본 시각은 SQLite `CURRENT_TIMESTAMP`이며 응답에는 UTC 오프셋이 없습니다. 프론트는 이를 방/메시지 정렬에 사용하고 시각은 표시하지 않습니다. `/api/auth/me`는 DB 문자열을 직접 반환하므로 공백 구분 형태(`YYYY-MM-DD HH:MM:SS`)일 수 있습니다.

## 2. 엔드포인트

| 메서드·경로 | 인증 | 성공 | 역할 |
|---|---|---|---|
| POST `/api/auth/register` | 없음 | 201 | 가입 |
| POST `/api/auth/login` | 없음 | 200 | JWT 발급 |
| GET `/api/auth/me` | 필수 | 200 | 내 계정 |
| POST `/api/chat` | 필수 | 200 | 질문·AI 응답 저장 |
| GET `/api/me/chats` | 필수 | 200 | 본인의 전체 대화 로그 |
| GET `/api/health` | 없음 | 200 | 앱 상태 응답 |

보조 경로도 존재합니다: `GET /health` → `{"status":"ok"}`, `GET /api/auth/status` → `{"status":"auth_router_ready"}`, `GET /api/chat/status` → `{"status":"chat_router_ready"}`. 모두 무인증 상태 확인이며 AI·DB 전체 정상 여부를 진단하지 않습니다. `/`와 `/static/`은 웹 UI 제공 경로입니다.

## 3. 가입·로그인·내 계정

가입 요청의 `username`은 원문 3~50자, 앞뒤 공백 제거 후 최소 3자입니다. 내부 공백은 별도 차단하지 않습니다. `password`는 원문 4~100자, 공백뿐인 값은 차단하며 앞뒤 공백을 제거하지 않습니다. 이는 현재 스키마 제한이며 모든 100자 비밀번호의 저장 성공 보장은 아닙니다. bcrypt의 바이트 길이 제약과 현행 검증의 차이는 [평가 가이드](evaluation_guide.md)의 후속 결함에서 추적합니다.

아래 자격 증명은 로컬 합성 예시이며 배포 계정이 아닙니다.

```json
{"username":"demo_user","password":"example-only-password"}
```

가입 성공:

```json
{"message":"회원가입이 완료되었습니다.","username":"demo_user"}
```

아이디 중복은 400 `{"detail":"이미 존재하는 아이디입니다."}`, 입력 형식/길이/검증 실패는 422입니다.

로그인도 같은 JSON 필드를 사용합니다. username은 앞뒤 공백을 제거하고 빈 값을 차단합니다. password는 빈 문자열을 차단하지만 공백뿐인 비밀번호는 별도 validator 차단 없이 인증 비교를 거칩니다. 자격 증명 불일치는 401입니다.

로그인 성공(토큰 문자열은 자리표시자):

```json
{"access_token":"<access_token>","token_type":"bearer"}
```

```json
{"detail":"아이디 또는 비밀번호가 올바르지 않습니다."}
```

인증 후 `GET /api/auth/me` 성공 예:

```json
{"id":1,"username":"demo_user","created_at":"2026-09-23 10:00:00"}
```

토큰 누락·위조·만료·해당 사용자 없음은 401 `{"detail":"인증 토큰이 유효하지 않거나 만료되었습니다."}`와 `WWW-Authenticate: Bearer`를 반환합니다. 프론트는 JWT를 `localStorage`에 저장합니다. 로그아웃 API는 없고 브라우저 토큰을 삭제하며 서버 측 즉시 폐기는 없습니다. 기본 만료는 `ACCESS_TOKEN_EXPIRE_MINUTES=1440`입니다.

## 4. 채팅 요청과 저장

`POST /api/chat` 요청:

| 필드 | 타입·제한 | 동작 |
|---|---|---|
| `question` | 필수 문자열, 공백 제거 전 최대 500자 | 앞뒤 공백 제거 후 빈 값은 라우터에서 400 |
| `conversation_id` | 선택 정수, 1 이상 또는 null | 생략/null은 새 방, 양의 ID는 본인 소유 기존 방 |

현재 프론트는 첫 질문에 ID 키를 **생략**합니다. 아래는 일반 여행 질문 예시이며 관광공사 조회 결과가 아닙니다.

```json
{"question":"반려동물과 국내여행 전에 확인할 사항을 알려주세요."}
```

성공 응답은 필수 3개 필드입니다. AI 성공 이후 DB 저장까지 성공해야 200을 반환합니다.

```json
{"conversation_id":1,"answer":"방문 시설의 동반 조건을 확인해 주세요.","latency_ms":520}
```

같은 방의 후속 요청:

```json
{"conversation_id":1,"question":"제가 방금 무엇을 물어봤나요?"}
```

처리 순서는 인증·입력 검증 → 방 소유권 검사 → 같은 방 최근 **5쌍**을 오래된 순서로 조회 → `generate_chat_response(question, history)` → DB 저장 → 응답입니다. 새 방은 history가 비어 있고 AI 성공 후 저장 단계에서 생성됩니다. 타인/없는 방은 AI 호출 전에 404입니다. 저장 함수도 소유권을 재확인합니다.

`latency_ms`는 AI 서비스 함수 구간을 측정한 0 이상의 정수이며 DB 읽기·쓰기와 전체 네트워크 왕복시간은 제외합니다. `AI_TIMEOUT_SECONDS` 기본 8.0은 httpx 네트워크 타임아웃 설정으로, 전체 요청의 절대 마감시간은 아닙니다. AI 실패 시 정상 Q/A는 저장하지 않으며 DB 저장 예외는 롤백합니다.

| 상태 | 상황 | 실제 `detail` |
|---|---|---|
| 400 | 유효한 인증 + 빈/공백 질문 | `질문 내용은 공백일 수 없습니다.` |
| 401 | 인증 실패 | `인증 토큰이 유효하지 않거나 만료되었습니다.` |
| 404 | 타인 또는 없는 방 | `접근할 수 있는 대화방을 찾지 못했습니다.` |
| 422 | 원문 500자 초과, 필수 필드 누락, 잘못된 형식/ID | 알려진 오류는 필드별 한국어 안내, 그 외는 `요청 데이터 형식이 올바르지 않습니다.` |
| 500 | 방 소유권/문맥 DB 조회 실패 | `대화 기록을 불러오지 못했습니다.` |
| 500 | 대화 DB 저장 실패 | `대화 기록을 저장하지 못했습니다.` |
| 502 | AI 네트워크·HTTP·응답 형식 등 오류 | `AI 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.` |
| 504 | AI 타임아웃 | `현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.` |

예를 들어 504 본문은 다음과 같습니다. 별도의 `error: AI_TIMEOUT` 필드는 현재 API에 없습니다.

```json
{"detail":"현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."}
```

미처리 예외는 공통 처리기가 500 `서버 내부 오류가 발생했습니다.`로 변환합니다. 여러 오류 조건을 한 요청에 겹쳤을 때 위 표의 행 순서가 응답 우선순위를 보장하지는 않습니다.

## 5. 본인 대화 이력

`GET /api/me/chats`는 `users → conversations → chat_logs` 관계에서 인증된 사용자의 로그를 **전체 평면 배열**로 반환합니다. `(created_at DESC, chat_log_id DESC)` 순서이며, 없으면 `[]`입니다. AI 문맥의 5쌍 제한이 이 API에 적용되지 않습니다. `ChatHistoryResponse` 래퍼 클래스는 현재 라우터의 응답 모델이 아닙니다.

```json
[
  {"id":2,"conversation_id":1,"title":"여행 준비","question":"제가 방금 무엇을 물어봤나요?","response":"여행 준비에 대해 물어보셨어요.","latency_ms":610,"created_at":"2026-09-23T10:00:30"},
  {"id":1,"conversation_id":1,"title":"여행 준비","question":"여행 준비","response":"방문 시설의 동반 조건을 확인해 주세요.","latency_ms":420,"created_at":"2026-09-23T10:00:00"}
]
```

`id`는 DB `chat_log_id`의 API 이름이며 `conversation_id`, `title`, `question`, `response`, `latency_ms`, `created_at`을 함께 반환합니다. 프론트가 방별로 묶고 각 방 메시지를 오래된 순서로 정렬합니다. 인증 오류는 401이며 DB 조회의 미처리 오류는 공통 500입니다.

## 6. 통합·확장 경계

프론트 통신은 [api.js](../static/js/api.js) 한 곳을 사용합니다. 첫 질문 → 응답 ID 수신 → 동일 ID로 후속 요청 → 전체 이력 재조회 계약을 지키고, 메시지 렌더링·계정 전환 경계는 [프론트 가이드](FRONTEND_GUIDE.md)를 따릅니다. 대역 채팅 응답에도 `conversation_id`, `answer`, `latency_ms`를 모두 넣습니다.

여행 장소·좌표·수요 API 및 구조화된 결과 필드는 **미구현**입니다. [여행 명세](pet_travel_spec.md)는 후속 설계이며 이 문서의 현행 엔드포인트 목록에 포함하지 않습니다. 로그·SQL·실제 검증 범위는 [평가 가이드](evaluation_guide.md)에서 확인합니다.
