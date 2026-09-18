# B7-1 AI 챗봇 개발 가이드라인 (AGENTS.md)

본 문서는 프로젝트 개발 시 모든 팀원(고준석, 박범규, 이준혁, 차종민)과 AI 에이전트가 영구적으로 준수해야 하는 공통 협업 및 기술 규칙입니다.

---

## 1. 프로젝트 기본 정보
- **서비스명**: AI Assistant (7-1 웹 기반 AI 챗봇)
- **프로젝트 목표**: 4일 내 핵심 컴포넌트(웹 UI ↔ 로그인/인증 ↔ FastAPI 백엔드 ↔ 코디세이 AI API ↔ SQLite DB ↔ AWS EC2 배포)가 100% 결합된 동작 가능한 프로토타입(MVP) 완성
- **개발 환경**: Python 3.10+, FastAPI, SQLite, Vanilla HTML/CSS/JavaScript
- **AI 연동**: 코디세이 AI API (GPT-4o-mini / Claude 3.5 Sonnet 호환 엔드포인트) + Mock AI Fallback 지원
- **배포 인프라**: AWS EC2 프리티어 (t2.micro / Ubuntu 22.04 LTS), 2GB Swap 메모리, Nginx 리버스 프록시, Systemd 데몬

---

## 2. 팀원 4인 역할 분담 (R&R)

| 팀원 | 담당 영역 | 세부 업무 내용 |
| :--- | :--- | :--- |
| **고준석**<br>(팀장) | **로그인 & 인증 (Auth)** | • 회원가입 API (POST /api/auth/register) 및 로그인 API (POST /api/auth/login)<br>• 비밀번호 bcrypt 해싱 및 JWT 토큰 발급/검증 유틸리티<br>• 미인증 사용자 401 차단용 FastAPI 의존성(get_current_user) 구현<br>• 전체 일정 관리 및 마일스톤 조율 (PM) |
| **박범규** | **백엔드 코어 & DB** | • FastAPI 메인 애플리케이션 진입점 및 라우터 통합 (app/main.py)<br>• SQLite DB 연결 및 테이블 스키마 (users, chat_logs)<br>• 대화 로그 저장 함수 및 내 대화 조회 API (GET /api/me/chats)<br>• 과제 필수 표준 4대 이벤트 로깅 모듈 및 scripts/check_logs.sql 작성 |
| **이준혁** | **프론트엔드 UI/UX** | • 반응형 단일 페이지 웹 챗봇 인터페이스 (static/index.html, style.css)<br>• 로그인 / 회원가입 모달 UI 및 JWT 로컬 스토리지 보관 처리 (auth.js)<br>• 실시간 질문 입력, 로딩 인디케이터, AI 응답 렌더링 스크립트 (app.js)<br>• 에러 알림 토스트 및 모바일/데스크탑 반응형 레이아웃 구성 |
| **차종민** | **AI 파이프라인** | • 코디세이 AI API 연동 모듈 (app/ai_service.py) 구축<br>• 최근 대화 3~5쌍을 조합하는 슬라이딩 윈도우 문맥(Context) 유지 전략 구현<br>• 8.0초 타임아웃 예외 핸들링 및 서버 프로세스 다운 방지 로직<br>• 키 미설정 및 테스트용 내장 Mock AI 엔진 구현 |

---

## 3. 4일 프로토타입 완성 마일스톤

- **Day 1 (독립 모듈 세팅 & AI PoC)**:
  - 브랜치 생성 (feat/auth-ko, feat/backend-park, feat/ui-lee, feat/ai-cha)
  - [차종민] 코디세이 AI API 단독 호출 PoC 스크립트 작성 및 8초 타임아웃 검증
  - [고준석] bcrypt 암호화 및 JWT 토큰 생성 유틸 함수 작성
  - [박범규] FastAPI 기본 서버 세팅 및 SQLite 스키마(users, chat_logs) 생성
  - [이준혁] 반응형 채팅 웹 UI HTML/CSS 와이어프레임 작성
- **Day 2 (코어 로직 & API 완성)**:
  - [고준석] 회원가입/로그인 엔드포인트 및 get_current_user 의존성 완성
  - [박범규] 대화 로그 DB 저장 함수, GET /api/me/chats 구현, 표준 4대 로깅 세팅
  - [이준혁] 로그인/회원가입 모달 완성, 토큰 저장 및 백엔드 비동기 통신 연동
  - [차종민] 슬라이딩 윈도우 문맥 조립, 8초 타임아웃 방어, Mock AI 모드 구현
- **Day 3 (전체 E2E 결합 - Alpha Release)**:
  - 인증 미들웨어 + 채팅 라우터 결합
  - UI에서 질문 입력 시 토큰 검증 -> 백엔드 수신 -> AI 호출 -> DB 저장 -> 화면 출력 전체 파이프라인 1차 통합
  - 통합 PR 생성 및 코드 리뷰 후 develop 브랜치 머지
- **Day 4 (안정성 강화 & 프로토타입 시연 검증)**:
  - 비정상 입력(공백, 500자 초과) 유효성 검사 차단
  - 타임아웃/API 에러 시 사용자 친절 안내(504) 연동
  - scripts/check_logs.sql로 SQLite 로그 검증
  - AWS EC2 프리티어 인프라 세팅(Nginx, Swap 2GB, Systemd) 및 외부 접속 시연 점검

---

## 4. 코드 및 주석 작성 규칙 (Self-Audit Guardrail)

1. **언어 규칙**:
   - 코드 docstring 및 모든 주석은 **100% 한국어**로 작성합니다. (영문 docstring 금지)
   - 변수명, 함수명, 클래스명은 명확한 표준 영어(snake_case, PascalCase)를 사용합니다.
2. **경로 표기 최우선 규칙**:
   - 문서, 코드, 산출물 내 경로 표기 시 절대 경로(file:///...)를 엄격히 금지하며, 항상 **상대 경로(예: B7-1/7-1/app/...)**로만 작성합니다.
3. **간결성 원칙 (Simplicity First)**:
   - 불필요하게 무거운 외부 프레임워크(LangChain 등)를 배제하고, FastAPI + httpx + SQLite + 바닐라 JS 기반의 직관적인 코드를 유지합니다.
4. **인코딩 및 제어문자 오염 방지 규칙**:
   - 모든 파일은 UTF-8(Without BOM)로 저장합니다.
   - 역슬래시(`\`)와 영문자가 결합되어 의도치 않은 ASCII 제어문자(`\a`, `\b`, `\f`, `\t`, `\r`)로 변환되지 않도록 경로 표기 시 항상 슬래시(`/`)를 사용하고, 스크립트 작성 시 Raw String(`r"..."`)을 사용합니다.

---

## 5. 보안 및 설정 가드레일 (Security First)

1. **민감 정보 절대 노출 금지**:
   - 코디세이 AI API Key, JWT Secret Key, DB 파일 등 모든 민감 정보는 소스코드에 하드코딩하지 않습니다.
   - 반드시 .env 파일과 환경 변수를 사용하며, .gitignore에 .env 및 *.db를 반드시 등록합니다.
   - 공개 저장소에는 .env.example만 제공합니다.
2. **AWS EC2 프리티어 인프라 보안**:
   - 보안 그룹 인바운드 규칙: SSH(22)는 팀원 IP 한정, HTTP(80)만 전체 오픈합니다.
   - FastAPI 포트(8000)를 외부에 직접 개방하지 않고, 앞단의 Nginx 리버스 프록시를 통해서만 전달합니다.
   - 메모리 1GB의 t2.micro 특성상 OOM 크래시를 방지하기 위해 **반드시 2GB Swap 파티션**을 구성합니다.
3. **비밀번호 단방향 암호화**:
   - 사용자 비밀번호는 절대 평문으로 저장하지 않고 bcrypt로 솔팅 및 해싱하여 저장합니다.
4. **엔드포인트 접근 제어**:
   - 챗봇 질의응답(POST /api/chat) 및 로그 조회(GET /api/me/chats)는 반드시 유효한 JWT 토큰이 검증된 로그인 사용자만 접근할 수 있도록 401 Unauthorized를 반환합니다.

---

## 6. 표준 로깅 규격 (과제 필수 요구사항 5항)

서버 로그는 Python 표준 logging 모듈을 사용하며, 아래 4대 핵심 이벤트 규격 포맷을 반드시 준수합니다:
```text
INFO request_received user_id={user_id} path={path}
INFO ai_call_start user_id={user_id} request_id={request_id}
INFO ai_call_success request_id={request_id} latency_ms={latency_ms}
INFO db_save_success user_id={user_id} chat_id={chat_id}
ERROR ai_call_failed request_id={request_id} error={error_detail}
ERROR db_save_failed user_id={user_id} error={error_detail}
```

---

## 7. 예외 처리 및 안정성 규칙

1. **AI API 호출 타임아웃**:
   - 코디세이 AI 호출 시 timeout=8.0초를 설정하여 무한 대기를 방지합니다.
   - 타임아웃 또는 API 에러 발생 시 FastAPI 프로세스가 다운되지 않고, 사용자에게 504 Gateway Timeout과 친절한 오류 안내(현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.)를 반환합니다.
2. **사용자 입력 검증**:
   - 빈 문자열 또는 공백만 있는 질문 차단 (400 Bad Request).
   - 최대 500자 길이 초과 질문 차단 (422 Unprocessable Entity).

---

## 8. Git 협업 및 커밋 컨벤션

1. **브랜치 전략**:
   - main: 배포용 프로덕션 브랜치 (직접 푸시 금지, PR 필수)
   - develop: 개발 통합 브랜치
   - feat/{기능명}-{이름}: 개인 작업 브랜치 (예: feat/auth-ko, feat/backend-park, feat/ui-lee, feat/ai-cha)
2. **커밋 메시지 형식**:
   - feat: 새로운 기능 구현
   - fix: 버그 수정
   - docs: 문서 작성 및 수정
   - style: 코드 포맷팅 및 주석 정리
   - refactor: 비즈니스 로직 리팩토링
   - test: 테스트 코드 및 검증 스크립트 추가
3. **팀원별 10회 커밋 룰**:
   - 전 팀원(4명)은 구현, 테스트, 리팩토링, 문서화를 작은 단위로 나누어 **최소 10회 이상의 유의미한 커밋**을 반드시 기록합니다.

## 9. Git & 작업 규칙 (Git Workflow)

- **커밋 단위 분리 (Atomic Commits)**
  - 대규모 일괄 커밋은 지양하고, 논리적이고 의미 있는 단위로 나누어 커밋합니다.
  - 기능 구현, 리팩터링, 버그 수정 등 작업 성격별로 분리하여 커밋 기록을 명확히 유지합니다.

- **이슈 및 PR 규칙 (Issues & Pull Requests)**
  - 푸시 후 이슈 발행 및 PR 생성 시 반드시 프로젝트의 기본 템플릿(`.github/ISSUE_TEMPLATE`, `.github/PULL_REQUEST_TEMPLATE`)을 준수합니다.
  - 템플릿의 필수 항목(작업 내용, 관련 이슈 링크, 테스트 결과 등)을 누락 없이 작성합니다.