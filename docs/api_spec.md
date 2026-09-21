# B7-1 웹 기반 AI 챗봇 REST API 명세서 (API Contract)

> **문서 버전**: v1.0.0  
> **최종 수정일**: 2026-09-15  
> **기본 Base URL**: `/api` (로컬 테스트: `http://localhost:8000/api`)  
> **대화형 문서**: `http://localhost:8000/docs` (Swagger UI), `http://localhost:8000/redoc` (ReDoc)  
> **관련 소스 파일**: `B7-1/7-1/app/schemas.py`, `B7-1/7-1/app/routers/`

---

## 1. 개요 및 공통 통신 규칙 (Global Conventions)

본 문서는 프론트엔드(`static/`)와 백엔드(`app/`) 간 데이터 통신 접지면을 사전에 확정하여, 병렬 개발 시 발생할 수 있는 필드 불일치 및 통신 에러를 방지하기 위한 **API 규약(API Contract)**입니다.

### 1.1 HTTP 요청/응답 헤더
- **요청 Body 포맷**: `Content-Type: application/json; charset=utf-8`
- **응답 Body 포맷**: `Content-Type: application/json; charset=utf-8`
- **인증 헤더 (보안 엔드포인트 필수)**:
  ```http
  Authorization: Bearer <access_token>
  ```

### 1.2 날짜 및 시간 포맷
- 모든 일시는 **ISO 8601** 문자열 형식을 따릅니다.
- 포맷: `YYYY-MM-DDTHH:MM:SS` (예: `2026-09-15T22:45:00`)

### 1.3 표준 오류 응답 형식 (Common Error Response)
모든 에러 상황(4xx, 5xx)에서 백엔드는 일관된 JSON 구조로 오류 원인을 반환합니다:
```json
{
  "detail": "오류 상세 설명 메시지"
}
```

---

## 2. API 엔드포인트 요약 (Overview)

| 번호 | 메서드 | URI 경로 | 인증 필요 | 기능 설명 | 성공 응답 |
| :---: | :---: | :--- | :---: | :--- | :---: |
| 1 | `POST` | `/api/auth/register` | X | 신규 사용자 회원가입 | `201 Created` |
| 2 | `POST` | `/api/auth/login` | X | 사용자 로그인 및 JWT 토큰 발급 | `200 OK` |
| 3 | `POST` | `/api/chat` | **O (필수)** | AI 챗봇 질문 전송 및 답변 수신 | `200 OK` |
| 4 | `GET` | `/api/me/chats` | **O (필수)** | 로그인 사용자의 대화 이력 목록 조회 | `200 OK` |
| 5 | `GET` | `/api/health` | X | 서버 상태 및 가용성 확인 (헬스체크) | `200 OK` |

---

## 3. 상세 엔드포인트 규격

### 3.1 [POST] 회원가입 (`/api/auth/register`)
신규 사용자 계정을 생성합니다. 비밀번호는 서버에서 `bcrypt` 단방향 해싱 후 저장됩니다.

- **URL**: `/api/auth/register`
- **Method**: `POST`
- **Authentication**: 없음

#### Request Body
| 필드명 | 타입 | 필수 여부 | 유효성 제약 | 설명 |
| :--- | :---: | :---: | :--- | :--- |
| `username` | `string` | **필수** | 3자 이상 50자 이하, 공백 불가 | 사용자 로그인 아이디 |
| `password` | `string` | **필수** | 4자 이상 100자 이하 | 계정 비밀번호 |

```json
{
  "username": "codyssey123",
  "password": "password1234"
}
```

#### Success Response (`201 Created`)
```json
{
  "message": "회원가입이 완료되었습니다.",
  "username": "codyssey123"
}
```

#### Error Response
- **400 Bad Request** (아이디 중복 또는 공백):
  ```json
  {
    "detail": "이미 존재하는 아이디입니다."
  }
  ```
- **422 Unprocessable Entity** (유효성 검사 실패):
  ```json
  {
    "detail": "아이디는 최소 3자 이상이어야 합니다."
  }
  ```

---

### 3.2 [POST] 로그인 및 JWT 발급 (`/api/auth/login`)
아이디와 비밀번호를 검증하고, 이후 인증 요청에 사용할 JWT 액세스 토큰을 발급합니다.

- **URL**: `/api/auth/login`
- **Method**: `POST`
- **Authentication**: 없음

#### Request Body
| 필드명 | 타입 | 필수 여부 | 유효성 제약 | 설명 |
| :--- | :---: | :---: | :--- | :--- |
| `username` | `string` | **필수** | 공백 불가 | 사용자 로그인 아이디 |
| `password` | `string` | **필수** | 공백 불가 | 계정 비밀번호 |

```json
{
  "username": "codyssey123",
  "password": "password1234"
}
```

#### Success Response (`200 OK`)
프론트엔드는 수신한 `access_token`을 `localStorage`에 보관하고 이후 API 호출 헤더에 첨부합니다.
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

#### Error Response
- **401 Unauthorized** (자격 증명 불일치):
  ```json
  {
    "detail": "아이디 또는 비밀번호가 올바르지 않습니다."
  }
  ```

---

### 3.3 [POST] AI 챗봇 질문 전송 (`/api/chat`)
로그인된 사용자가 질문을 전송하면, 백엔드는 최근 대화 문맥을 조합하여 AI API를 호출하고 응답과 응답 시간(latency_ms)을 반환하며 SQLite DB에 기록합니다.

- **URL**: `/api/chat`
- **Method**: `POST`
- **Authentication**: **필수** (`Authorization: Bearer <access_token>`)

#### Request Headers
```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsIn...
Content-Type: application/json; charset=utf-8
```

#### Request Body
| 필드명 | 타입 | 필수 여부 | 유효성 제약 | 설명 |
| :--- | :---: | :---: | :--- | :--- |
| `question` | `string` | **필수** | 1자 이상 500자 이하, 공백 불가 | 사용자가 질문할 내용 |

```json
{
  "question": "이번 주 프로젝트 4일 일정 요약해줘."
}
```

#### Success Response (`200 OK`)
| 필드명 | 타입 | 설명 |
| :--- | :---: | :--- |
| `answer` | `string` | AI 모델이 생성한 답변 내용 |
| `latency_ms` | `integer` | AI API 처리 및 응답 생성 소요 시간 (밀리초) |

```json
{
  "answer": "이번 주 4일 프로토타입 프로젝트 일정은 Day 1 독립 모듈 세팅, Day 2 코어 로직 완성, Day 3 E2E 결합, Day 4 안정성 점검 및 배포 순서로 진행됩니다.",
  "latency_ms": 520
}
```

#### Error Response
- **400 Bad Request** (공백 질문 입력):
  ```json
  {
    "detail": "질문 내용은 공백일 수 없습니다."
  }
  ```
- **401 Unauthorized** (토큰 누락, 위변조 또는 만료):
  ```json
  {
    "detail": "인증 토큰이 유효하지 않거나 만료되었습니다."
  }
  ```
- **422 Unprocessable Entity** (500자 초과 등):
  ```json
  {
    "detail": "질문은 최대 500자까지 입력 가능합니다."
  }
  ```
- **502 Bad Gateway** (Gemini API 오류 또는 응답 형식 오류):
  ```json
  {
    "detail": "AI 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."
  }
  ```
- **504 Gateway Timeout** (AI API 호출 8.0초 초과):
  ```json
  {
    "detail": "현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
  }
  ```

---

### 3.4 [GET] 내 대화 이력 목록 조회 (`/api/me/chats`)
로그인한 본인의 대화 기록 목록을 최신순으로 반환합니다. 프론트엔드는 화면 표시 시 시간순으로 정렬할 수 있습니다.

- **URL**: `/api/me/chats`
- **Method**: `GET`
- **Authentication**: **필수** (`Authorization: Bearer <access_token>`)

#### Request Headers
```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsIn...
```

#### Request Body
- 없음

#### Success Response (`200 OK`)
대화 객체의 배열(`Array<ChatLogItem>`) 형태로 반환됩니다.
```json
[
  {
    "id": 1,
    "question": "안녕?",
    "response": "안녕하세요! AI 어시스턴트입니다.",
    "latency_ms": 420,
    "created_at": "2026-09-15T20:45:00"
  },
  {
    "id": 2,
    "question": "너의 역할은 뭐야?",
    "response": "저는 사용자의 질문에 친절하고 정확하게 답변해 드리는 챗봇입니다.",
    "latency_ms": 610,
    "created_at": "2026-09-15T20:45:30"
  }
]
```

#### Error Response
- **401 Unauthorized**:
  ```json
  {
    "detail": "인증 토큰이 유효하지 않거나 만료되었습니다."
  }
  ```

---

### 3.5 [GET] 서버 헬스체크 (`/api/health`)
서버 인스턴스가 정상 동작 중인지 확인하는 헬스체크 엔드포인트입니다.

- **URL**: `/api/health`
- **Method**: `GET`
- **Authentication**: 없음

#### Success Response (`200 OK`)
```json
{
  "status": "ok"
}
```

---

## 4. 프론트엔드 연동 가이드 (Frontend Integration Guide)

프론트엔드 담당(이준혁)은 백엔드 완성 전이라도 아래 표준 통신 함수 패턴과 테스트 대역을 사용하여 UI를 독립적으로 검증할 수 있습니다.

### 4.1 인증 토큰 관리 및 공통 Fetch 래퍼 (예시)
```javascript
// static/js/auth.js 또는 static/js/app.js
const API_BASE = '/api';

// 인증 헤더 획득 함수
function getAuthHeader() {
  const token = localStorage.getItem('access_token');
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

// 챗봇 질문 비동기 전송 함수
async function sendChatMessage(question) {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeader(),
    },
    body: JSON.stringify({ question }),
  });

  if (response.status === 401) {
    alert('로그인이 만료되었습니다. 다시 로그인해주세요.');
    localStorage.removeItem('access_token');
    showLoginModal();
    return null;
  }

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || '채팅 요청 처리에 실패했습니다.');
  }

  return data; // { answer: "...", latency_ms: 520 }
}
```

### 4.2 프론트엔드 계약 테스트용 예시 응답 데이터
백엔드 서버 연동 전 로컬 브라우저 단독 테스트에서 아래 예시 데이터를 활용하여 채팅 버블 렌더링, 로딩 인디케이터 동작, 에러 토스트 피드백을 검증할 수 있습니다:

```javascript
// 계약 테스트용 응답 예시
const TEST_CHAT_RESPONSE = {
  answer: "안녕하세요! 계약 테스트용 예시 답변입니다.",
  latency_ms: 350
};
```
