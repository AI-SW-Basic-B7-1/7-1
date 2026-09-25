# B7-1 웹 기반 AI 챗봇 4일 프로토타입 초기 프로젝트 계획서

> 문서 성격: 프로젝트 시작 당시의 4일 MVP 계획을 보존한 기록입니다. 현재 구현 상태와 반려동물 여행 확장 계획은 [중기 프로젝트 계획](midterm_project_plan.md)을 따릅니다.
>
> 참고: 아래 초기 일정의 코디세이·Mock AI 표기는 계획 당시의 기록입니다. 현재 구현 기준은 Gemini API이며 제품 실행 중 Mock AI fallback은 사용하지 않습니다.

> **프로젝트명**: AI Assistant (7-1 웹 기반 AI 챗봇 서비스)
>
> **개발 기간**: 4일 집중 완성 (Day 1 ~ Day 4)
>
> **목표**: 4일 내 핵심 컴포넌트(웹 UI ↔ 로그인/인증 ↔ FastAPI 백엔드 ↔ 코디세이 AI API ↔ SQLite DB ↔ AWS EC2 배포)가 100% 결합된 동작 가능한 프로토타입(MVP) 완성

---

## 1. 프로젝트 개요 및 범위

### 1.1 프로젝트 개요
본 프로젝트는 사용자가 웹 브라우저에서 로그인 후 실시간으로 AI 챗봇과 대화를 나누고, 이전 대화의 문맥(Context)을 유지하며 응답을 제공받는 웹 기반 AI 서비스입니다. 모든 대화 기록은 SQLite DB에 영속적으로 저장되며, 표준화된 4대 핵심 서버 로깅과 AI 호출 타임아웃 방어 체계를 갖추어 안정적인 운영을 보장합니다.

### 1.2 핵심 개발 범위 (Scope)
- **인증 및 접근 제어**: 회원가입, 로그인, bcrypt 단방향 암호화, JWT 토큰 발급 및 엔드포인트 인가
- **AI 대화 파이프라인**: 코디세이 AI API(OpenAI 호환 GPT-4o-mini) 비동기 호출, 슬라이딩 윈도우(최근 3~5쌍) 문맥 조합, 8.0초 타임아웃 방어, Mock AI 엔진
- **데이터베이스 및 로깅**: SQLite users/chat_logs 모델링, 대화 이력 저장/조회 API, 4대 핵심 이벤트 로깅
- **웹 인터페이스**: 반응형 단일 페이지 챗봇 UI, 로그인/회원가입 모달, 비동기 REST 통신
- **인프라 및 배포**: AWS EC2 프리티어(t2.micro), 2GB Swap 메모리, Nginx 리버스 프록시, Systemd 상시 구동

---

## 2. 팀 구성원 및 역할 분담 (R&R)

| 팀원 | 담당 역할 | 핵심 개발 영역 |
| :--- | :--- | :--- |
| **고준석** (팀장) | **로그인 & 인증 (Auth) / PM** | • 회원가입(POST /api/auth/register), 로그인(POST /api/auth/login), 내 정보 조회(GET /api/auth/me) API<br>• 비밀번호 bcrypt 단방향 해싱 및 JWT 액세스 토큰 발급/검증 로직<br>• 미인증 사용자 접근 차단용 FastAPI Dependency (get_current_user) 구현<br>• 인증 라우터 비동기 통합 테스트 스위트(tests/test_auth_router.py) 구축<br>• 프로젝트 전체 일정 조율 및 마일스톤 관리 |
| **박범규** | **백엔드 코어 & DB (Chat Owner)** | • FastAPI 메인 애플리케이션 진입점 및 라우터 통합 (app/main.py)<br>• **POST /api/chat 엔드포인트 전체 흐름 최종 소유**: 요청 검증(공백/글자수), 인증 확인, ai_service 호출, 응답시간(latency_ms) 측정, DB 저장 및 에러 핸들링<br>• SQLite DB 연결 및 테이블 스키마 (users, chat_logs) 구축, 내 대화 이력 조회 API (GET /api/me/chats)<br>• 표준 4대 이벤트 로깅 모듈, DB 검증용 scripts/check_db_chats.sql 및 서버 로그 검증 스크립트 작성 |
| **이준혁** | **프론트엔드 UI/UX** | • 단일 페이지 반응형 웹 챗봇 인터페이스 (static/index.html, style.css)<br>• 로그인 및 회원가입 모달 UI, JWT 로컬 스토리지 보관 및 헤더 전송 (auth.js)<br>• 실시간 메시지 버블 렌더링, 로딩 인디케이터, 비동기 API 통신 (app.js)<br>• Day 1~2 Mock API 기반 조기 E2E 연동 및 에러 토스트 피드백 |
| **차종민** | **AI 파이프라인 (Service Provider)** | • **웹/DB 의존성이 배제된 순수 비동기 함수 모듈**(app/ai_service.py: generate_chat_response) 제공<br>• 최근 대화 3~5쌍을 조합하는 슬라이딩 윈도우 문맥(Context) 유지 전략 구현<br>• 8.0초 타임아웃 예외 핸들링 및 서버 프로세스 다운 방지 로직 (504 반환 규격 준수)<br>• 외부 키 미설정 시에도 시연 및 평가가 가능한 내장 Mock AI 엔진 구현 |

---

## 3. 4일간의 일자별 상세 마일스톤

```text
[Day 1] 독립 모듈 & Mock API 세팅 ──> [Day 2] 코어 로직 & 조기 Mock E2E ──> [Day 3] 실제 AI/DB 결합 ──> [Day 4] 안정성 & 시연 점검
```

### Day 1: 독립 컴포넌트 뼈대 세팅 & 조기 Mock 통신 준비
- **공통 목표**: 개인별 작업 브랜치 생성 및 각자 영역의 베이스라인 구축, Day 2 조기 연동을 위한 Mock 엔드포인트 선행 오픈
- **작업 브랜치**: feat/auth-ko, feat/backend-park, feat/ui-lee, feat/ai-cha
- **세부 태스크**:
  - [고준석] 비밀번호 bcrypt 해싱 및 JWT 토큰 생성 유틸리티 함수 작성 (app/auth.py)
  - [박범규] FastAPI 기본 골격 생성, SQLite 스키마(users, chat_logs) 세팅, **조기 연동용 Mock 응답 엔드포인트(POST /api/chat 더미 응답, GET /api/health) 우선 배포**
  - [이준혁] 반응형 채팅 인터페이스 HTML/CSS 와이어프레임 작성 및 백엔드 Mock 엔드포인트 비동기 fetch 통신 준비 (static/index.html, static/css/style.css, static/js/app.js)
  - [차종민] 코디세이 AI API 단독 호출 PoC 스크립트 작성 및 8초 타임아웃 사전 검증 (app/ai_service.py)

### Day 2: 각자 담당 코어 완성 & [조기 Mock E2E 관통]
- **공통 목표**: 컴포넌트 핵심 로직 완성 및 **프론트↔백엔드 간 조기 Mock E2E 연동(Walking Skeleton)을 완통하여 통합 리스크 조기 제거**
- **세부 태스크**:
  - **[조기 E2E 통합]**: 프론트엔드 UI에서 질문 입력 시 백엔드 Mock 엔드포인트로 전송되어 화면에 답변 말풍선과 지연시간이 렌더링되는 전 과정을 Day 2에 선제적으로 확인 (CORS, 헤더, JSON 파싱 오류 사전 차단)
  - [고준석] 회원가입/로그인/내 정보 조회 엔드포인트 및 get_current_user 인증 의존성 완성 (app/routers/auth_router.py), 인증 라우터 비동기 통합 테스트 스위트 작성 (tests/test_auth_router.py)
  - [박범규] POST /api/chat 메인 라우터 로직(유효성 검사, latency 측정, DB 저장), GET /api/me/chats 구현, 표준 4대 로깅 포맷터 적용 (app/logger.py, app/routers/chat_router.py)
  - [이준혁] 로그인/회원가입 모달 UI 완성, 토큰 로컬스토리지 저장 및 백엔드 비동기 통신 연동 (static/js/auth.js)
  - [차종민] 웹/DB와 분리된 순수 비동기 함수 형태의 AI 생성기 완성(문맥 조립, 8초 타임아웃 방어, Mock AI 엔진) (app/ai_service.py)

### Day 3: 실제 백엔드-프론트엔드-AI 전체 결합 (Alpha Release)
- **공통 목표**: Day 2에 이미 검증된 E2E 파이프라인 상의 Mock 응답을 **실제 코디세이 AI API 및 SQLite DB 영속 저장으로 교체 결합**
- **세부 태스크**:
  - [박범규 + 차종민] POST /api/chat 라우터 내부에서 차종민의 ai_service.generate_chat_response 비동기 함수를 호출하고 응답 결과를 SQLite chat_logs 테이블에 자동 저장
  - [고준석 + 박범규] POST /api/chat 및 GET /api/me/chats에 get_current_user 인증 의존성(current_user: UserInDB = Depends(get_current_user))을 결합하여 실제 로그인한 사용자 식별자(user_id) 기반 대화 저장 연동
  - [이준혁 + 팀 전원] 브라우저 UI에서 실제 로그인 -> 질문 전송 -> 실제 AI 답변 수신 -> DB 저장 -> 대화 이력(GET /api/me/chats) 갱신 전 과정 실데이터 E2E 검증
  - [공통] 통합 PR 생성, 상호 코드 리뷰 후 develop 브랜치에 머지

### Day 4: 안정성 강화, 입력 검증 & 프로토타입 최종 점검
- **공통 목표**: 예외 방어 및 인프라 배포를 완료하고 시연 준비 완료
- **세부 태스크**:
  - [고준석] 비로그인 사용자 및 만료된 토큰 요청 시 401 차단 동작 자동화 테스트(pytest) 검증 완료
  - [박범규] 공백 입력(400) 및 500자 초과 비정상 입력(422) 차단 검증, **SQLite DB 검증(scripts/check_db_chats.sql)** 및 **서버 텍스트 로그 검증(scripts/check_server_logs.sh)** 수행
  - [차종민] AI 타임아웃 발생 시 504 안내 메시지 UI 연동 및 Mock AI 정상 구동 테스트
  - [이준혁] 에러 토스트 피드백, 로딩 스피너 및 반응형 UI 최종 디테일 보완
  - [팀 전원] AWS EC2 인프라 세팅(Nginx, 2GB Swap, Systemd) 및 외부 접속 시연 점검

---

## 4. 리스크 관리 및 대응 방안

| 리스크 요인 | 영향도 | 사전 예방 및 대응 방안 |
| :--- | :---: | :--- |
| **AWS EC2 t2.micro 메모리 부족 (OOM)** | 높음 | 1GB RAM 한계 극복을 위해 OS 설치 직후 **2GB Swap 메모리**를 즉시 생성하여 프로세스 강제 종료를 사전에 차단합니다. |
| **코디세이 AI API 지연 및 무한 대기** | 높음 | 모든 외부 AI 호출에 timeout=8.0초를 강제 설정하고, 실패 시 504 안내 메시지를 반환하여 서버 프로세스가 다운되지 않도록 격리합니다. |
| **프론트-백엔드 늦은 결합으로 인한 통합 병목** | 높음 | Day 3 대신 **Day 1~2에 Mock 엔드포인트 기반 E2E 연동(Walking Skeleton)을 선제 완료**하여 CORS, 토큰 전달, JSON 불일치를 조기에 제거합니다. |
| **평가자 환경의 API 키 부재** | 중간 | CODESSEY_API_KEY가 설정되지 않았을 때도 서비스 시연이 가능하도록 내장 Mock AI 엔진을 기본 탑재합니다. |
| **브랜치 병합 시 코드 충돌 및 모듈 혼선** | 중간 | `POST /api/chat` 라우터 소유권(백엔드)과 AI 생성 로직(AI 담당자 순수 함수)의 책임을 엄격히 분리하여 독립 개발합니다. |
