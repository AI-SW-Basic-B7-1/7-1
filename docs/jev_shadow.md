# Jev AI 관찰 모드

기존 `POST /api/chat`은 Gemini 답변을 생성하고 저장합니다. `JEV_MODE=shadow`를 명시하면 저장 성공 뒤 백그라운드에서 [TypeSafe Jev API](https://docs.typesafe.ai/api)에 질문·최근 대화·답변을 보내 `accept`/`retry`/`review` 중 하나를 받습니다. 판정은 로그에만 남고 사용자 답변과 DB 내용에는 반영되지 않습니다. 기본값 `off`에서는 TypeSafe 요청이 없습니다.

## 키와 실행 설정

서버를 실행할 저장소 루트의 `.env`에 다음 값을 **직접** 입력합니다. 키를 채팅·이슈·PR·명령 인자에 넣지 않습니다. `.env`는 Git 추적 대상에서 제외됩니다.

```dotenv
TYPESAFE_API_KEY="발급받은 실제 키"
JEV_MODE="shadow"
JEV_MODEL="jev-1.13.0"
JEV_TIMEOUT_SECONDS="2.0"
```

Windows PowerShell에서 키 값을 출력하지 않고 설정 여부만 확인할 수 있습니다.

```powershell
python -c "from app.config import settings; print('TYPESAFE_API_KEY:', 'OK' if settings.TYPESAFE_API_KEY else 'MISSING')"
```

서버를 재시작해야 설정이 적용됩니다. 운영 중 즉시 JEV 호출을 중단하려면 `.env`에서 `JEV_MODE="off"`로 바꾸고 서버를 재시작합니다. `shadow`가 아닌 값도 호출을 시작하지 않지만, 설정값은 `off` 또는 `shadow`만 사용합니다.

`shadow`에서는 채팅 내용이 제3자 TypeSafe API로 전송됩니다. 실제 사용자 데이터에 적용하기 전에 서비스의 개인정보 안내와 처리 기준을 확인해야 합니다. 로그에는 원문 질문·문맥·답변이나 API 키를 기록하지 않고 요청 ID, 판정, confidence, 모델 버전, 호출 시간 또는 실패 유형만 기록합니다. Jev 오류나 전체 호출 상한 2초는 Gemini 답변을 502/504로 바꾸지 않습니다. 백그라운드 작업은 응답 후 실행되므로 사용자 응답을 기다리게 하지 않지만, 프로세스가 종료되면 판정 로그가 남지 않을 수 있습니다. API의 `latency_ms`는 검색 조건 분석, 관광 API 조회, 최종 답변 생성까지 측정하며 DB 읽기·쓰기는 제외합니다.

## 연결 확인

서버 실행과 별도로, 예시 질문 한 건을 실제 Jev에 보내려면 다음을 실행합니다. 이 명령은 `JEV_MODE=off`여도 진단 목적으로 API를 호출합니다.

```powershell
python scripts/check_jev.py
```

정상 응답에는 요청·응답 모델, 판정, confidence, 호출 시간이 표시됩니다. 키가 없으면 외부 호출 없이 종료합니다. 연결 오류에는 HTTP 응답 본문이나 키를 출력하지 않습니다. 공식 문서상 엔드포인트는 `POST /v1/systemone`, 인증 방식은 Bearer이고 Choice 응답에는 `choice`와 `confidence`가 포함됩니다.

채팅의 shadow 판정, 연결 점검, 비교 도구는 모두 `JEV_TIMEOUT_SECONDS`의 같은 전체 호출 시간 제한을 사용합니다. 시간 초과는 세 경로에서 모두 `timeout` 실패로 처리됩니다.

## 같은 사례로 비교

```powershell
python scripts/benchmark_jev.py --cases tests/fixtures/jev_cases.jsonl --repeat 3
```

JSONL의 각 행은 `question`, `answer`, `expected_action`을 포함하고, 필요하면 최근 대화 `history`에 `question`·`response` 쌍을 넣습니다. `off`의 현재 동작 기준은 모든 답변을 `accept`로 간주합니다. `model` 지표는 성공한 Jev 호출만, `effective` 지표는 호출 오류 시 기존 답변을 통과시키는 결과까지 포함합니다. **False Accept**는 사람이 `retry` 또는 `review`로 판정한 사례 중 `accept`한 비율입니다. 추가 지연은 Jev 호출의 평균과 95백분위값으로 표시합니다.

저장소의 3개 fixture는 실행 형식을 보여주는 **예시**이며 사람이 검증한 평가셋이 아닙니다. 품질 향상 결론을 내려면 동일한 한국어 여행 사례 최소 30~50건에 사람이 `expected_action`을 붙이고, 애매한 정답은 합의한 뒤 결과를 재측정해야 합니다. Jev confidence나 예시 파일 점수만으로 정확도를 주장하지 않습니다. [공식 모델 문서](https://docs.typesafe.ai/models)는 영어가 주 학습 언어이고 CJK 성능은 같은 수준으로 보장하지 않는다고 밝힙니다.

이 비교는 **판정 분류 성능**을 측정합니다. `shadow`가 사용자에게 보여주는 Gemini 답변 자체를 개선했다는 지표가 아닙니다.
