#  AI 챗봇 개발 가이드라인

본 문서는 프로젝트 개발 시 모든 팀원과 AI 에이전트가 영구적으로 준수해야 하는 공통 규칙입니다.

---

## 1. 프로젝트 기본 정보
- **서비스명**: 미정
- **목적**:. 실시간 AI 챗봇 웹 서비스
- **기술 스택**: Python 3.10+, FastAPI, SQLite / Vanilla JS, 코디세이 AI API (GPT-4o-mini / Claude 3.5 Sonnet)
- **배포 인프라**: AWS EC2 프리티어 (Ubuntu 22.04 LTS), Nginx

---

## 2. 코드 및 주석 작성 규칙 (Self-Audit Guardrail)
1. **언어 규칙**:
   - 코드 docstring 및 모든 주석은 **100% 한국어**로 작성합니다. (영문 docstring 금지)
   - 변수명, 함수명, 클래스명은 명확한 영어(snake_case, PascalCase)를 사용합니다.
2. **경로 표기 최우선 규칙**:
   - 문서, 코드, 산출물 내 경로 표기 시 절대 경로(`file:///...`)를 엄격히 금지하며, 항상 **상대 경로(예: `B7-1/output_gemini/...`)**로만 작성합니다.
3. **간결성 원칙 (Simplicity First)**:
   - 10일 일정에 맞게 복잡한 외부 프레임워크(LangChain 등)를 배제하고, 직관적인 FastAPI + 경량 DB 검색 + 프롬프트 주입 방식을 유지합니다.

---

## 3. 보안 및 설정 가드레일 (Security First)
1. **민감 정보 절대 노출 금지**:
   - 코데세이 AI API Key, DB 접속 정보 등 모든 민감 정보는 소스코드에 하드코딩하지 않습니다.
   - 반드시 `.env` 파일과 환경 변수를 사용하며, `.gitignore`에 `.env` 및 `*.db`를 반드시 등록합니다.
   - 공개 저장소에는 `.env.example`만 제공합니다.
2. **비밀번호 단방향 암호화**:
   - 사용자 비밀번호는 평문으로 저장하지 않고 `bcrypt` 또는 `passlib`를 사용해 해싱하여 SQLite에 저장합니다.
3. **엔드포인트 보안**:
   - 챗봇 질의응답 및 로그 조회 엔드포인트는 반드시 로그인 세션/토큰이 검증된 사용자만 접근할 수 있도록 차단합니다.

---

## 4. 로깅 규격 (과제 필수 요구사항 5항)
서버 로그에는 Python 표준 `logging` 모듈을 사용하며, 아래 규격 포맷을 반드시 준수합니다:
```text
INFO request_received user_id={user_id} path={path}
INFO ai_call_start user_id={user_id} request_id={request_id}
INFO ai_call_success request_id={request_id} latency_ms={latency_ms}
INFO db_save_success user_id={user_id} chat_id={chat_id}
ERROR ai_call_failed request_id={request_id} error={error_detail}
```

---

## 5. 예외 처리 및 안정성 규칙
1. **AI API 호출 타임아웃**:
   - 코데세이 AI 호출 시 `timeout=8.0`초를 설정하여 무한 대기를 방지합니다.
   - 타임아웃 또는 API 에러 발생 시 서버가 죽지 않고, 사용자 화면에 친절한 오류 안내(예: `현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.`)와 에러 코드를 반환합니다.
2. **사용자 입력 검증**:
   - 빈 문자열 또는 공백만 있는 질문 차단.
   - 최대 500자 길이 제한 적용.

---

## 6. Git 협업 및 커밋 컨벤션
1. **브랜치 전략**:
   - `main`: 배포용 안정 브랜치 (직접 푸시 금지)
   - `develop`: 팀 통합 브랜치
   - `feat/{기능명}-{이름}`: 개인별 작업 브랜치
2. **커밋 메시지 형식**:
   - `feat: 새로운 기능 구현`
   - `fix: 버그 수정`
   - `docs: 문서 작성 및 수정`
   - `style: 코드 포맷팅 및 주석 정리`
   - `refactor: 비즈니스 로직 리팩토링`
   - `test: 테스트 코드 및 검증 스크립트 추가`
3. **팀원별 10회 커밋 룰**:
   - 전 팀원(4명)은 기능 구현, 테스트, 리팩토링, 문서화를 잘게 쪼개어 최소 10회 이상의 유의미한 커밋을 남깁니다.
