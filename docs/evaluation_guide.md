# Term Project 평가·검증 가이드

> 과제: AI/SW 기초 · Term Project · 필수 · 120시간 · 웹 기반 AI 챗봇 서비스(FastAPI)
> 조사 기준: 2026-09-23, `develop` = `755e7e2d4bface034b4c1ed318505a0c32ca1818`.
> **문서 정비와 기존 구현의 검증 기록입니다. 미션 전체 합격·실 AI 시연·관광/지도 구현 완료를 뜻하지 않습니다.**

## 1. 요구사항 추적

| 미션 요구사항 | 현재 근거 | 이번 확인 범위 | 남은 확인 |
|---|---|---|---|
| 웹 질문 입력·같은 화면 응답 | `static/index.html`, `static/js/app.js`, `api.js` | 프론트 단위·정적 계약 37개 및 공개 자원 GET | 실제 브라우저 전체 흐름 |
| 회원가입·로그인·접근 제어 | `app/auth.py`, `app/routers/auth_router.py` | 합성 DB 인증 테스트, 미인증 401 | 운영 로그인, 만료 검증 보강 #55 |
| 로그인 사용자만 채팅 | `Depends(get_current_user)`, 방 소유권 | 타인 방 AI 호출 전 404·사용자별 이력 분리 테스트 | 운영 두 계정 시연 |
| FastAPI 서버 AI 호출·키 비공개 | `app/ai_service.py`, `app/config.py` | Gemini 요청 조립/실패 처리 대역 테스트 | 실제 계정 키·모델 응답 |
| 최소 문맥 유지 | `get_recent_chat_logs_by_conversation(limit=5)` | 같은 방 5쌍·새 방/계정 분리 테스트 | 실제 모델의 후속 답변 확인 |
| 사용자·시간·질문·응답 누적 저장 | `users → conversations → chat_logs`, `save_chat_log` | 임시 DB 저장·조회·마이그레이션·롤백 테스트 | 재접속 후 운영 이력 복원 |
| 사용자 기준 로그 조회 | `GET /api/me/chats`, SQL JOIN | 본인 전체 배열·사용자별 SQL 2/1건 확인 | 평가 계정 API/SQL 증빙 |
| 요청·AI 호출·성공/실패·DB 저장 이벤트 | `app/routers/chat_router.py`, `app/logger.py` | 로거 및 성공/실패 이벤트 테스트, 실제 경로 `logs/app.log` | 운영 파일 로그, #17 스크립트 수정 |
| AI 실패·타임아웃·오류 안내·서버 유지 | `AITimeoutError`, 공통 예외 처리 | 대역 502/504, DB 500 및 이후 health 성공 | 실패 후 정상 채팅까지 연속 검증 #16/#19 |
| 입력 검증 | `app/schemas.py`, 채팅 라우터 | 빈/공백 400, 500자 초과 422 테스트 | 브라우저 입력/오류 안내 시연 |
| 외부 접속 가능 URL | `http://15.164.49.77/` | 아래 시각에 페이지·자원·health 200, 무토큰 이력 401 | 평가 직전 재확인·실 배포 SHA |
| 실행/환경 변수/민감정보 | `.env.example`, `.gitignore`, README | 실제 설정 키 7개 대조 | 기본 JWT 키·ignore 누락 보강, HTTPS 검토 |
| 브랜치·기능 작업·PR 병합 | main/develop 및 기능 브랜치, 병합 PR | 전체 PR 목록과 대표 변경·Git 이력 확인 | 팀 최종 제출 기준 확인 |
| 팀원별 유의미한 커밋 10회 이상 | 아래 author별 비머지 집계 | 종민 author 4개, 전원 달성 확인 불가 | 추가 실질 기여·별도 author 여부 확인 |
| 역할·개인별 요약 | README·중기 프로젝트 계획과 대표 PR | 실제 파일·병합 기록 대응 | 개인별 설명 및 최종 역할 확인 |
| 개요·아키텍처·API·DB·배포·DB 확인 패키지 | README에서 관련 문서 연결 | 문서·상대 링크·JSON/API 계약 점검 | 실 AI·외부 시연 증빙 추가 |

반려동물 데이터·지역 수요·Google Maps는 팀 주제의 추가 기능입니다. 미션의 공통 필수 API인 것처럼 취급하지 않으며 세 기능 모두 현재 미구현입니다.

## 2. 코드와 문서 불일치 처리

| 이전 문서 주장/첨부 초안 | 코드·PR 근거 | 반영 |
|---|---|---|
| 4일이 전체 과제 기간, 코디세이·내장 Mock | 120시간 미션, #29 Gemini 전환 | 초기 계획 원문을 보존하고 README·중기 계획·AGENTS에서 현재 구현 분리 |
| `logs/server.log`, 로그 검증 스크립트 사용 가능 | config/logger의 `logs/app.log`, #17 변수 누락 | README·배포·평가 가이드에 직접 로그 조회 |
| 가입/채팅 422의 필드별 detail | `validation_exception_handler`의 고정 문자열 | API 명세의 오류 예시 수정 |
| 사용자 이력도 최근 5건 | #37의 방 문맥 LIMIT 5, 전체 이력 쿼리에는 LIMIT 없음 | API·README에 전체 배열 계약 유지; #52는 미병합 종료 |
| 배포 스크립트 develop 미반영 | #44/#48 병합, scripts/ec2 3개 존재 | 배포 문서의 오래된 전제 수정 |
| 첨부 초안의 배포 기본값 develop | `run_ec2_deploy.sh`의 `DEPLOY_BRANCH` 기본값 main | 기존 코드를 우선, `--branch develop` 명시 안내 |
| 여행·지도 기능처럼 보일 수 있는 기획 | 관련 런타임 모듈·설정·테스트 없음 | 후속 명세 및 미구현 상태로 표시 |
| 팀원별 10회 달성 표현 | 비머지 author 집계 | 요구사항과 실제 확인값 구분 |

## 3. 이번 실행 결과

Python 3.12.13 / Node.js 24.21.0 / macOS x86_64, 운영 키·운영 DB 없이 격리된 임시 환경에서 실행했습니다. Node는 공식 배포 파일의 SHA-256을 확인한 임시 설치본을 사용했습니다. 저장소 런타임 의존성 파일은 변경하지 않았습니다.

| 명령/검증 | 결과·한계 |
|---|---|
| `python -m pip install -r requirements.txt` | 임시 venv 설치 성공. 하한만 지정된 의존성이므로 다른 시점에는 버전이 달라질 수 있음 |
| `python -m pytest -q` | **45 passed** (9.94초). Gemini는 대역; 운영 DB/실 AI 아님 |
| `node --test tests/frontend/*.test.mjs` | **37 passed**, 실패/skip 0. 실제 브라우저 E2E 아님 |
| `scripts/check_db_chats.sql`, `scripts/check_logs.sql` | 앱 스키마로 만든 빈 DB·합성 데이터 DB에서 각각 성공, 총 4회 |
| 사용자별 JOIN, Python `mode=ro` | 합성 사용자 A 2건/B 1건 분리 확인, 무결성 ok·외래키 위반 없음 |
| 문서 상대 링크·JSON 예시 | 상대 링크 43개·JSON 코드 블록 12개 점검, 현행 Pydantic 모델과 대조 통과 |
| 문서 API 계약 | 격리 ASGI 가입/로그인/me/채팅/전체 이력 및 422 실제 응답 필드 대조 통과 |
| 평가 가이드 Python 예시 | 이 문서의 코드 블록을 임시 합성 DB 경로에서 실행, 사용자 분리 확인 |
| `git diff --check` | 통과; 변경 범위는 Markdown 8개, 실제 키·DB·런타임 코드 추가 없음 |
| 가입 스키마와 bcrypt 경계 | 73 ASCII 바이트 비밀번호가 스키마를 통과하지만 bcrypt 5.0.0 해시에서 ValueError; 격리 ASGI 가입에서도 500 재현 |
| `.gitignore` 실제 매칭 | `.env`, `.env.local`, `data/chatbot.db` 제외. `.env.production`, `data/chatbot.db-wal`, `data/chatbot.db-shm`은 제외 안 됨 |

주요 설치 버전: FastAPI 0.141.1, Starlette 1.7.0, Pydantic 2.13.5, httpx 0.28.1, aiosqlite 0.22.1, PyJWT 2.14.0, bcrypt 5.0.0, pytest 9.1.1, pytest-asyncio 1.4.0. 과거 첨부 문서의 Python 3.12.14 / Node 24.19.0 결과와 이번 결과를 혼동하지 않습니다.

이 환경의 SQLite CLI 3.43.2에서는 WAL 보조 파일 없는 DB에 `-readonly`만 사용하면 열기 오류가 났습니다. 일반 CLI로 기존 조회 전용 SQL을 실행하고, 별도로 Python `mode=ro` 사용자 조회를 검증했습니다. 보조 파일 생성 가능 여부와 DB 디렉터리 권한을 확인하고 활성 WAL 파일을 임의로 삭제하지 않습니다.

### 공개 HTTP 확인

시각: **2026-09-23 11:09:43 UTC / 20:09:43 KST**. 실행 환경에서 외부 공개 주소로 GET 요청했습니다.

| 대상 | 상태 |
|---|---|
| `/` | 200, HTML |
| `/static/css/style.css` | 200, CSS |
| `/static/js/api.js`, `auth.js`, `app.js`, `history.js`, `keyboard.js`, `chat-content.js`, `shell.js` | 모두 200, JavaScript |
| `/api/health` | 200, `{"status":"ok"}` |
| `/api/me/chats` (토큰 없음) | 401 |

배포된 SHA는 응답으로 확인되지 않아 **미확인**입니다. 이 점검은 실제 로그인·AI 응답·DB 쓰기·브라우저 렌더링·운영 복원·관광 API·지도 SDK 검증을 포함하지 않습니다. EC2 배포나 운영 설정 변경도 수행하지 않았습니다.

## 4. DB 확인 방법

### 본인 이력 API

로그인한 평가용 합성 계정으로 `GET /api/me/chats`를 요청합니다. Bearer 토큰을 공개 터미널 기록에 직접 적지 않습니다. 아래 `ACCESS_TOKEN`은 로컬 세션에서만 설정하고 결과의 개인 대화를 공개하지 않습니다.

```bash
curl -sS -H "Authorization: Bearer ${ACCESS_TOKEN}" http://127.0.0.1:8000/api/me/chats
```

응답은 `[{"id":1,"conversation_id":1,"title":"합성 질문","question":"합성 질문","response":"합성 답변","latency_ms":100,"created_at":"2026-09-23T10:00:00"}]` 형태입니다. 빈 계정은 `[]`이며 다른 계정의 기록이 섞이지 않아야 합니다. 자세한 요청·응답은 [API 명세](api_spec.md)에 있습니다.

### 기존 SQL

저장소 루트에서 실제 DATABASE_URL이 가리키는 파일을 확인합니다. 아래 기본 파일이 없다면 명령으로 빈 DB를 만드는 대신 경로를 먼저 고칩니다.

```bash
test -f data/chatbot.db && sqlite3 data/chatbot.db < scripts/check_db_chats.sql
```

이 스크립트는 SELECT로 전체 건수, 최근 10건의 질문/응답 앞 30자, 사용자별 집계를 조회합니다. `scripts/check_logs.sql`은 호환용 동일 SQL이며 삭제하지 않았습니다. 질문/답변 전체를 사용자 기준으로 확인할 때는 다음 Python 읽기 전용 예를 사용합니다. 변수 `target_user_id`와 DB 경로는 평가용 합성 계정/실제 설정에 맞춥니다.

```python
from pathlib import Path
import sqlite3

# 저장소 루트 기준 경로를 사용하고 없는 DB를 생성하지 않습니다.
db_path = Path("data/chatbot.db")
if not db_path.is_file():
    raise SystemExit("DB 경로를 먼저 확인하세요.")
target_user_id = 1
query = """
SELECT c.user_id, c.conversation_id, cl.chat_log_id,
       cl.created_at, cl.question, cl.response, cl.latency_ms
FROM chat_logs AS cl
JOIN conversations AS c ON c.conversation_id = cl.conversation_id
WHERE c.user_id = ?
ORDER BY cl.created_at ASC, cl.chat_log_id ASC;
"""
connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
try:
    for row in connection.execute(query, (target_user_id,)):
        print(row)
finally:
    connection.close()
```

대화 로그에는 직접 user_id 열이 없으며 conversations를 JOIN해 추적합니다. DB 직접 조회는 접근 권한이 있는 운영자/평가자용이며 공개 관리자 API를 추가한 것이 아닙니다. 원본 DB·WAL·백업·사용자 출력은 Git에 넣지 않습니다.

## 5. 서버 로그 확인과 실패 추적

프로젝트 루트에서 다음 명령을 실행합니다. 파일은 `logs/app.log`, 회전은 5MiB × 백업 3개입니다. 콘솔도 같은 형식으로 기록하며 EC2에서는 `journalctl -u chatbot.service`로 볼 수 있습니다.

```bash
grep -E 'request_received|ai_call_start|ai_call_success|ai_call_failed|db_save_success|db_save_failed|db_read_failed' logs/app.log
```

인증·질문 검증을 통과한 채팅 요청에 request_received가 기록됩니다. 모든 HTTP 요청을 수집하는 접근 로그는 아닙니다. AI 시작/성공/실패는 request_id, DB 성공은 user_id/chat_id로 확인합니다. 현재 모든 이벤트에 공통 request_id가 있지는 않습니다. 실패한 AI 요청은 성공 Q/A 행으로 남지 않습니다.

`scripts/check_server_logs.sh`와 `.ps1`에는 변수 누락이 있으므로 위 직접 조회를 사용하고 [#17](https://github.com/AI-SW-Basic-B7-1/7-1/issues/17)에서 수정합니다. 예외 원인 로그는 내부 확인에 사용하되 비밀값·대화 내용을 검토 없이 공개하지 않습니다.

## 6. 평가 시연 절차와 남은 증빙

1. 배포 담당자가 배포 커밋(`git rev-parse HEAD`), 환경 이름, URL, 확인 시각을 기록합니다. 키 값은 기록하지 않습니다.
2. 외부 브라우저에서 페이지·정적 파일·health를 확인합니다. 비로그인 채팅/이력 요청 401을 확인합니다.
3. 합성 계정 A로 가입·로그인 후 첫 질문을 전송하고 실제 Gemini 응답·conversation_id·지연시간을 확인합니다.
4. 같은 방에서 “제가 방금 무엇을 물어봤나요?”를 질문합니다. 새 방은 이전 방 문맥이 섞이지 않아야 합니다.
5. 6쌍 이상 대화 뒤에도 이력은 모두 남고 AI 입력은 최근 5쌍인지 확인합니다.
6. 로그아웃·재로그인/페이지 재접속 후 해당 방 이력을 확인하고 SQL의 사용자·시간·질문·응답과 대조합니다.
7. 합성 계정 B로 전환해 A의 방/캐시/로그가 보이지 않고 A의 방 ID를 요청하면 404인지 확인합니다.
8. 공백/500자 초과·만료 토큰, AI 타임아웃/오류, DB 실패를 **격리된 검증 환경**에서 재현합니다. 운영 DB를 손상시키거나 서비스 키를 폐기해 시험하지 않습니다. 안내·실패 로그·부분 저장 없음·그 다음 정상 채팅 성공을 확인합니다.
9. 팀 역할, 기능 브랜치, PR 병합 기록, 개인별 유의미한 커밋 10회 증빙을 제출합니다. 미달/미확인 항목을 숨기지 않습니다.

기록 형식: `시각 / 환경·URL / 배포 SHA / 시나리오 / 실제 결과 / 성공·실패 / 비밀값 제거한 증빙 / 남은 이슈`. 대역 결과와 실 API 결과를 분리합니다. 여행 확장은 [후속 명세](pet_travel_spec.md)의 실 조회·누락·오류·지도·복원 인수 기준을 추가로 적용합니다.

## 7. 협업 이력과 개인별 커밋

현재 기본/통합 브랜치는 `develop`, 배포용 원칙은 `main`입니다. 기준 develop은 `755e7e2`, main은 `0be74ae1a07d5e70770f0617181ae131c8734879`로 서로 다릅니다. 기능 브랜치와 병합 PR의 근거는 [중기 프로젝트 계획](midterm_project_plan.md)의 역할 표를 봅니다. 프로젝트 시작 당시의 역할·일정은 [초기 프로젝트 계획](project_plan.md)에 별도로 보존합니다.

기준 SHA에 도달 가능한 **비머지 커밋의 Git author 이름**으로 집계했습니다. 이는 커밋 개수이며 각 커밋의 의미나 개인 학습량을 자동 보장하지 않습니다. 이번 문서 브랜치의 새 커밋은 아래 기준 집계에 포함하지 않습니다.

| Git author | 비머지 수 | 매핑·평가 상태 |
|---|---:|---|
| kjs83036 | 43 | 고준석, 인증/배포/검증 PR 확인 |
| pbk98 | 37 | 박범규, 서버/DB/로깅 PR 확인 |
| Cerhovah | 32 | 이준혁, UI/계약 테스트/문서 PR 확인 |
| jongmin | 4 | 차종민의 GitHub whdals006 및 #29/#35/#41로 확인. 이 범위에서는 10회 미달 |
| jun_seok_ko | 1 | Initial commit `5ad4b2d`, GitHub kjs83036 연결 확인. 의미 검토 없이 10회 증빙에 가산하지 않음 |
| 이준혁 | 1 | Node 요구사항 문서 `8d7ea8b`, GitHub author 매핑 없음. 이름만으로 추가 합산하지 않음 |
| Codex | 1 | 개인 기여에 임의 합산하지 않음 |

조회 시 가져온 모든 원격 브랜치의 author 이름도 확인했으며 jongmin 비머지 커밋은 여전히 4개였습니다. 별도 author나 다른 저장소 기여의 동일인 여부는 확정하지 않았습니다. 따라서 개인 총기여가 4개라고 단정하지 않으며, **전원 10회 달성 증빙은 미완료**입니다. 실제 기능·테스트·문서 작업으로 충족하고 빈 커밋을 만들지 않습니다.

```bash
git fetch origin
git shortlog -sn --no-merges 755e7e2d4bface034b4c1ed318505a0c32ca1818
git log --no-merges --format='%h %an %s' 755e7e2d4bface034b4c1ed318505a0c32ca1818
git log --all --no-merges --author=jongmin --format='%h %an %s'
```

조사 시 열린 PR은 0개였습니다. #37/#41/#44/#46/#48/#51/#53/#54는 병합됐으며 #52는 병합 없이 닫혔습니다. 이슈 #40이 열려 있어도 #41의 예외 처리 코드가 미구현인 것은 아닙니다. #42의 전체 이력 LIMIT 5 제안은 현행 UI 전체 복원 계약과 충돌하므로 별도 설계 검토가 필요합니다.

## 8. 남은 작업과 이슈

| 항목 | 추적·현재 상태 |
|---|---|
| 문서 정비 | [#56](https://github.com/AI-SW-Basic-B7-1/7-1/issues/56), 이번 PR 범위. 기능 이슈는 이 PR로 종료하지 않음 |
| 반려동물 조회·근거 결합 | [#57](https://github.com/AI-SW-Basic-B7-1/7-1/issues/57), 미구현 |
| 지역 수요 PoC·지역/기간 매핑 | [#58](https://github.com/AI-SW-Basic-B7-1/7-1/issues/58), 미구현 |
| Google Maps·좌표/복원 계약 | [#59](https://github.com/AI-SW-Basic-B7-1/7-1/issues/59), 미구현 |
| JWT 기본값·ignore 누락·비밀번호 바이트 검증 | [#60](https://github.com/AI-SW-Basic-B7-1/7-1/issues/60). SECRET_KEY를 반드시 직접 설정하며 인증 가드레일 보강은 후속 작업 |
| 로그 스크립트 | [#17](https://github.com/AI-SW-Basic-B7-1/7-1/issues/17), 이번에는 실행 코드 수정 없음 |
| DB SQL/최종 평가 증빙 | [#18](https://github.com/AI-SW-Basic-B7-1/7-1/issues/18), 임시 DB 검증과 운영 확인을 구분 |
| 전체 실 AI·브라우저·외부 배포 검증 | [#19](https://github.com/AI-SW-Basic-B7-1/7-1/issues/19), [#26](https://github.com/AI-SW-Basic-B7-1/7-1/issues/26) |
| 예외·실패 이후 정상 요청 | [#16](https://github.com/AI-SW-Basic-B7-1/7-1/issues/16), [#40](https://github.com/AI-SW-Basic-B7-1/7-1/issues/40), #41 구현과 잔여 검증 구분 |
| 만료 토큰 검증 | [#55](https://github.com/AI-SW-Basic-B7-1/7-1/issues/55): 실제 존재 사용자로 만료만의 효과 검증 필요 |
| 이력 성능 | [#42](https://github.com/AI-SW-Basic-B7-1/7-1/issues/42), 전체 이력과 AI 문맥의 책임 구분 필요 |

추가 관찰: 가입의 문자 수 제한과 bcrypt 72바이트 제한이 달라 긴 비밀번호가 500으로 이어질 수 있습니다. [#60](https://github.com/AI-SW-Basic-B7-1/7-1/issues/60)에서 바이트 경계·다국어·사용자 안내를 보강해야 합니다. HTTP 주소·localStorage 토큰·서버 로그아웃 폐기 부재는 현재 교육용 MVP의 운영 한계입니다. EC2의 고정 DB 검사/백업 경로와 사용자 지정 DATABASE_URL의 일치 여부도 #26의 운영 점검 대상으로 남깁니다.

PR 준비 직전 원격을 다시 fetch했으며 develop은 기준 SHA 그대로이고 열린 다른 PR은 0개였습니다. 기존 계약은 보존하며 #42의 전체 이력 제한 제안은 이번 문서에 적용하지 않았습니다. 최종 병합 가능 상태는 GitHub PR에서 확인합니다.
