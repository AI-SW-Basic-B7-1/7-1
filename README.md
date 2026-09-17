# AI Assistant (7-1 웹 기반 AI 챗봇 서비스)

> **과제명**: B7-1 웹 기반 AI 챗봇 서비스 개발 프로젝트  
> **프로젝트 목표**: 사용자 인증, 코디세이 AI API 비동기 연동, 대화 문맥 유지, SQLite 영속 저장 및 4대 표준 로깅을 결합한 4일 단기 완성 웹 챗봇 프로토타입(MVP)

---

## 1. 팀 구성원 및 역할 분담 (R&R)

전 팀원은 각자의 담당 영역을 독립적으로 개발하고, PR 기반 머지 및 1인당 최소 10회 이상의 커밋을 달성합니다.

| 팀원 | 담당 역할 | 세부 업무 내용 및 기여 영역 |
| :--- | :--- | :--- |
| **고준석** (팀장) | **로그인 & 인증 (Auth) / PM** | • 회원가입(`POST /api/auth/register`) 및 로그인(`POST /api/auth/login`) API<br>• 비밀번호 `bcrypt` 단방향 해싱 및 JWT 액세스 토큰 발급/검증 로직<br>• 미인증 사용자 접근 차단용 FastAPI Dependency (`get_current_user`) 구현<br>• 프로젝트 전체 일정 조율 및 마일스톤 관리 |
| **박범규** | **백엔드 코어 & DB (Chat Owner)** | • FastAPI 메인 애플리케이션 진입점 및 라우터 통합 (`app/main.py`)<br>• **`POST /api/chat` 엔드포인트 전체 흐름 최종 소유**: 요청 검증(공백/500자 제한), 인증 확인, AI 서비스 호출, 응답시간(`latency_ms`) 측정, DB 저장 및 에러 핸들링<br>• SQLite DB 연결 및 테이블 스키마 (`users`, `chat_logs`) 설계/구축, 내 대화 이력 조회 API (`GET /api/me/chats`)<br>• 표준 4대 이벤트 로깅 모듈, DB 검증용 `scripts/check_db_chats.sql` 및 서버 로그 검증 스크립트 작성 |
| **이준혁** | **프론트엔드 UI/UX** | • 단일 페이지 반응형 웹 챗봇 인터페이스 (`static/index.html`, `style.css`)<br>• 로그인 및 회원가입 모달 UI, JWT 로컬 스토리지 보관 및 헤더 전송 (`auth.js`)<br>• 실시간 메시지 버블 렌더링, 로딩 인디케이터, 비동기 API 통신 (`app.js`)<br>• Day 1~2 Mock API 기반 조기 E2E 연동 및 에러 토스트 피드백 |
| **차종민** | **AI 파이프라인 (Service Provider)** | • **웹/DB 의존성이 배제된 순수 비동기 함수 모듈**(`app/ai_service.py`: `generate_chat_response`) 제공<br>• 최근 대화 3~5쌍을 조합하는 슬라이딩 윈도우 문맥(Context) 유지 전략 구현<br>• 8.0초 타임아웃 예외 핸들링 및 서버 프로세스 다운 방지 로직 (504 반환 규격 준수)<br>• 외부 키 미설정 시에도 시연 및 평가가 가능한 내장 Mock AI 엔진 구현 |

---

## 2. 시스템 아키텍처

```text
[ 사용자 브라우저 ]
        │ HTTP (80)
        ▼
[ AWS EC2 t2.micro (Ubuntu 22.04 LTS) ]
 ├── [ Nginx 리버스 프록시 ] (Port 80 -> Port 8000 라우팅 및 정적 리소스 서빙)
 └── [ Uvicorn + FastAPI ] (Port 8000 로컬 바인딩, Systemd 서비스 데몬 구동)
      ├── [ 인증 미들웨어 ] (JWT 토큰 유효성 검증, 미인증 시 401 차단)
      ├── [ AI 파이프라인 ] (문맥 조립 -> 8초 타임아웃 -> 코디세이 AI API / Mock AI)
      ├── [ 표준 로거 ] (4대 핵심 이벤트 실시간 콘솔/파일 기록)
      └── [ SQLite DB ] (users, chat_logs 테이블 / WAL 모드)
```

---

## 3. 4일 프로토타입 개발 일정 (마일스톤 요약)

```text
[Day 1] 독립 모듈 & Mock API 세팅 ──> [Day 2] 코어 로직 & 조기 Mock E2E ──> [Day 3] 실제 AI/DB 결합 ──> [Day 4] 안정성 & 시연 점검
```

- **Day 1**: 독립 컴포넌트 뼈대 세팅, 단독 PoC 검증, **조기 연동용 Mock 응답 엔드포인트 선행 배포**
- **Day 2**: 각자 코어 로직 완성 및 **프론트↔백엔드 간 조기 Mock E2E 연동(Walking Skeleton) 완료** (통합 리스크 조기 제거)
- **Day 3**: 백엔드-프론트엔드-AI 전체 파이프라인에 **실제 AI API 및 SQLite DB 영속 저장 교체 결합** (Alpha Release)
- **Day 4**: 안정성 강화, 입력 검증, SQLite DB 무결성/서버 로그 검증, EC2 배포 및 프로토타입 시연 점검

👉 **일자별 상세 태스크 및 체크리스트**: [docs/project_plan.md](docs/project_plan.md) 참고

---

## 4. 데이터베이스 구조 (Data Schema)

SQLite 데이터베이스 파일 경로: `data/chatbot.db`

DB 초기화 시 `PRAGMA journal_mode = WAL` 및 `PRAGMA foreign_keys = ON`을 적용합니다.

### 4.1 users 테이블
| 필드명 | 타입 | 제약 조건 | 설명 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 사용자 고유 번호 |
| `username` | VARCHAR(50) | UNIQUE, NOT NULL | 로그인 아이디 |
| `hashed_password` | VARCHAR(255) | NOT NULL | bcrypt 단방향 암호화된 비밀번호 |
| `created_at` | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | 계정 생성 일시 |

### 4.2 chat_logs 테이블
| 필드명 | 타입 | 제약 조건 | 설명 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 대화 로그 고유 번호 |
| `user_id` | INTEGER | NOT NULL, FK(users.id) ON DELETE CASCADE | 대화를 진행한 사용자 식별자 |
| `question` | TEXT | NOT NULL | 사용자가 입력한 질문 |
| `response` | TEXT | NOT NULL | AI가 생성한 응답 텍스트 |
| `latency_ms` | INTEGER | NOT NULL, DEFAULT 0 | AI API 호출 소요 시간 (밀리초) |
| `created_at` | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | 대화 기록 일시 |

`chat_logs` 테이블은 사용자별 최신 대화 조회를 위해 `(user_id, created_at DESC)` 인덱스를 생성합니다.

---

## 5. API 명세 (핵심 엔드포인트)

| 메서드 | 엔드포인트 | 인증 필요 | 설명 | 요청 예시 | 응답 예시 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register` | X | 신규 회원가입 | `{"username": "testuser", "password": "pass1234"}` | `201 Created` |
| `POST` | `/api/auth/login` | X | 로그인 및 JWT 토큰 발급 | `{"username": "testuser", "password": "pass1234"}` | `{"access_token": "eyJ...", "token_type": "bearer"}` |
| `POST` | `/api/chat` | **O (필수)** | AI 질문 전송 및 답변 수신 | `{"question": "안녕? 너는 누구야?"}` | `{"answer": "안녕하세요! AI 어시스턴트입니다.", "latency_ms": 450}` |
| `GET` | `/api/me/chats` | **O (필수)** | 본인 대화 이력 조회 | - | `[{"id": 1, "question": "...", "response": "...", "created_at": "..."}]` |
| `GET` | `/api/health` | X | 서버 헬스체크 | - | `{"status": "ok"}` |

👉 **엔드포인트별 상세 Request/Response JSON, Pydantic 스키마 및 상태 코드 규격**: [docs/api_spec.md](docs/api_spec.md) 참고

---

## 6. 설치 및 로컬 실행 방법

### 6.1 가상환경 생성 및 패키지 설치
```bash
# 가상환경 생성 (Python 3.10+)
python -m venv venv

# 가상환경 활성화 (Windows PowerShell)
.\venv\Scripts\Activate.ps1
# (Linux/macOS) source venv/bin/activate

# 필수 패키지 설치
pip install -r requirements.txt
```

#### 프론트엔드 테스트 사전 요구사항

프론트엔드 테스트 실행에는 Node.js가 필요합니다.

```bash
node --version
node --test tests/frontend/*.test.mjs
```

### 6.2 환경변수 설정
`.env.example` 파일을 복사하여 `.env` 파일을 생성하고 값을 설정합니다:
```bash
cp .env.example .env
```
`.env` 파일 내용:
```ini
# [보안 설정]
SECRET_KEY="your_super_secret_jwt_key_here"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# [데이터베이스 경로]
DATABASE_URL="sqlite:///./data/chatbot.db"

# [코디세이 AI API 설정 (500만 토큰 제공)]
CODESSEY_API_KEY="your_codessey_api_key"
CODESSEY_API_BASE="https://api.openai.com/v1"
AI_MODEL_NAME="gpt-4o-mini"
AI_TIMEOUT_SECONDS=8.0
```

### 6.3 로컬 개발 서버 실행
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
브라우저에서 `http://localhost:8000` 접속 시 웹 챗봇 화면이 서빙됩니다.

---

## 7. AWS EC2 프리티어 배포 및 인프라 가이드

### 7.1 인스턴스 사양 및 메모리 스왑 설정
*   **인스턴스**: AWS EC2 `t2.micro` (Ubuntu 22.04 LTS, RAM 1GB)
*   **2GB Swap 메모리 설정 (OOM 크래시 방지 필수)**:
    ```bash
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    ```

### 7.2 Nginx 리버스 프록시 설정
FastAPI 단독 노출 대신 80번 표준 포트 수신 후 내부 8000번 포트로 전달합니다:
```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### 7.3 Systemd 백그라운드 서비스 등록
SSH 세션 종료 후에도 서비스가 상시 구동되도록 systemd에 등록합니다.
`/etc/systemd/system/chatbot.service`:
```ini
[Unit]
Description=FastAPI AI Chatbot Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/7-1
ExecStart=/home/ubuntu/7-1/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 8. 운영 안정성 및 표준 로깅 체계

### 8.1 표준 4대 이벤트 서버 로깅 (Python logging)
서버 콘솔(stdout) 및 파일(`logs/server.log`)에 실시간으로 구조화된 4대 핵심 이벤트를 기록합니다:
```text
INFO request_received user_id=1 path=/api/chat
INFO ai_call_start user_id=1 request_id=req-98234
INFO ai_call_success request_id=req-98234 latency_ms=480
INFO db_save_success user_id=1 chat_id=102
```

- **서버 로그 검증 스크립트**: `scripts/check_server_logs.sh`
  ```bash
  # 4대 표준 로그 이벤트 실시간 필터링 확인
  bash scripts/check_server_logs.sh
  # 또는 직접 grep 실행
  grep -E "(request_received|ai_call_start|ai_call_success|db_save_success)" logs/server.log
  ```

### 8.2 SQLite DB 대화 이력 영속성 검증 (SQL)
RDBMS(`chat_logs` 테이블)에 누적 저장된 사용자 질문, AI 응답, 지연시간(`latency_ms`)을 검증합니다:
- **DB 검증 쿼리 스크립트**: `scripts/check_db_chats.sql`
  ```bash
  sqlite3 data/chatbot.db < scripts/check_db_chats.sql
  ```

### 8.3 AI 타임아웃 및 장애 복원력
- **8.0초 타임아웃 격리**: 코디세이 API 호출 지연 시 서버 프로세스가 다운되지 않고 즉시 504 Gateway Timeout 안내 응답을 반환합니다.
- **내장 Mock AI 엔진**: `CODESSEY_API_KEY` 미입력 환경에서도 서비스 정상 동작을 100% 시연할 수 있도록 모의 응답 폴백을 지원합니다.
