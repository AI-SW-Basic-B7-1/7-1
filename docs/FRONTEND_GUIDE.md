# 프론트엔드 실행·계약·이식 경계

이 문서는 `static/` 프론트엔드의 현재 실행 조건과 검증 근거를 설명합니다. 이번 작업에서는 개인 풀스택 저장소 안에서만 구현했으며, 팀 Organization 저장소로 복사하거나 백엔드를 재접합하지 않았습니다.

## 1. 파일 역할

| 경로 | 역할 |
|---|---|
| `static/index.html` | 로그인·가입 모달, 대화 목록, 질문 입력, 상태·오류 영역 |
| `static/css/style.css` | 데스크톱/모바일 레이아웃, 로딩·포커스·오류 상태 |
| `static/js/api.js` | 모든 `/api/...` fetch, Bearer, JSON·비JSON 응답 계약 |
| `static/js/auth.js` | 가입·로그인·토큰·모달·로그아웃·탭 간 세션 동기화 |
| `static/js/app.js` | 기록 조회, 질문 전송, 렌더링, 로딩·세션 경합 처리 |
| `static/js/keyboard.js` | Enter·Shift+Enter·IME 전송 판정 |

프론트 코드는 Python 모듈, 서버 템플릿, `.env`, 개인 DB 경로를 import하거나 읽지 않습니다. `fetch`는 `api.js` 한 곳에만 있고 동일 origin 상대 경로만 사용합니다.

## 2. 서버가 제공해야 하는 경로

- `GET /` → `static/index.html`
- `GET /static/css/style.css`
- `GET /static/js/api.js`
- `GET /static/js/auth.js`
- `GET /static/js/app.js`
- `GET /static/js/keyboard.js`

JavaScript는 ES module로 제공되어야 하며 올바른 JavaScript MIME type이 필요합니다. HTML을 `file://`로 직접 열지 않습니다. 현재 개인 서버에서는 FastAPI가 위 경로를 제공하며 실행 주소는 `http://127.0.0.1:8000`입니다.

정적 자원과 API는 `/static/...`, `/api/...` root-relative 경로입니다. 앱을 임의의 하위 URL에 배치하려면 팀 서버가 이 두 루트 경로를 그대로 연결하거나 합의된 rewrite를 제공해야 합니다.

## 3. 팀 API 접지면

| 기능 | 요청 | 성공 응답 | 프론트가 사용하는 필드 |
|---|---|---|---|
| 상태 | `GET /api/health` | 200 object | `status: "ok"` |
| 가입 | `POST /api/auth/register` | 201 object | `message`, `username` |
| 로그인 | `POST /api/auth/login` | 200 object | `access_token`, `token_type: "bearer"` |
| 채팅 | `POST /api/chat` + Bearer | 200 object | `answer`, `latency_ms` |
| 내 기록 | `GET /api/me/chats` + Bearer | 200 array | `id`, `question`, `response`, `latency_ms`, `created_at` |

가입·로그인은 JSON `{username, password}`, 채팅은 JSON `{question}`입니다. 오류는 앱 계약상 `{detail: "한국어 문자열"}`이며, 프록시 등 앱 밖의 비JSON 응답도 안전한 일반 문구로 처리합니다. 보호 API의 현재 요청에서만 401 세션 만료 처리를 합니다.

`X-AI-Mode`는 있으면 개발 모드 배지에 쓰는 선택 응답 헤더입니다. 이 헤더가 없어도 가입·로그인·채팅·기록 조회는 정상 동작합니다. 프론트는 요청에 `X-AI-Mode`를 보내지 않고 응답 body에 `mode` 필드가 있다고 가정하지 않습니다.

## 4. 상태·보안 경계

- 토큰 저장 key는 `access_token` 하나이며 비밀번호·질문은 저장소에 넣지 않습니다.
- 메시지는 `textContent`로 렌더링하고 HTML/Markdown을 실행하지 않습니다.
- 채팅 POST는 자동 재시도하지 않으며 요청당 fetch 1회입니다.
- 로그아웃·사용자 전환은 진행 요청을 abort하고 세션 generation/token을 대조해 늦은 응답을 버립니다.
- 다른 탭의 토큰 변경은 `storage` 이벤트로 동기화하지만 다시 저장하지 않아 이벤트 루프를 만들지 않습니다.
- `localStorage` 토큰은 XSS에 노출될 수 있습니다. 이 최소 구현은 CSP·HttpOnly cookie 전환을 포함하지 않습니다.
- 클라이언트 로그아웃은 브라우저 토큰만 삭제합니다. 이미 복사된 JWT를 서버에서 즉시 폐기하지 않으며 기본 만료는 1440분입니다.

## 5. 입력·접근성 동작

- 질문은 원문 Unicode code point 기준 최대 500자이며 공백-only는 거부합니다.
- Enter는 전송, Shift+Enter는 줄바꿈입니다. `isComposing` 또는 IME keyCode 229인 Enter는 전송하지 않습니다.
- 전송·기록 로딩 중 입력과 버튼을 잠그고 `aria-busy`를 갱신합니다.
- 모달은 Tab/Shift+Tab 포커스 경계를 유지하고 Escape로 닫은 뒤 로그인 버튼에 포커스를 돌립니다.
- 360×640 실제 브라우저에서 가로 overflow 없이 대화 목록 내부 스크롤과 composer 사용을 확인했습니다.

## 6. 실행과 검증

```powershell
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/Scripts/python.exe -m pytest tests/test_frontend_contract.py tests/test_api_contract.py -q
node --test tests/frontend/*.test.mjs
```

Node 경로는 환경에 따라 다를 수 있습니다. 브라우저 검증은 실제 로컬 API와 임시 테스트 DB에서 가입 → 로그인 → 채팅 → 재로그인 기록, 401/504/500/비JSON 복구, 사용자 A/B 전환, 두 탭 동기화, 모바일·키보드·HTML 문자열 저장 복원을 확인했습니다. 상세 실행 결과는 `docs/IMPLEMENTATION_STATUS.md`에 있습니다.

## 7. 추후 팀 저장소로 옮길 때

이번에는 아래 작업을 실행하지 않았습니다. 추후 승인된 팀 저장소에서 다음 순서로 진행합니다.

1. `static/`만 그대로 옮기고 상대 파일 구조를 유지합니다.
2. 팀 서버가 2절의 정적 경로와 3절의 API 계약을 제공하는지 먼저 테스트합니다.
3. 선택 헤더 없이 가입·로그인·채팅·기록이 통과하는지 확인합니다.
4. 계약이 다르면 `api.js` 접지면에서 팀 합의 후 조정하고 DOM 모듈에 endpoint를 흩뜨리지 않습니다.
5. 실제 팀 브랜치·PR·리뷰 이력은 개인 저장소의 현재 커밋과 별도로 기록합니다.
