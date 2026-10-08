# 반려동물 동반 국내여행 AI 챗봇 검토 요약

**기준: 2026-10-08, `origin/develop` `3f9ebab`**

## 서비스 목표

로그인한 사용자가 반려동물 동반 국내여행 정보를 질문하고, 확인된 장소·동반 조건을 대화로 살펴보는 웹 서비스를 제공합니다.

## 현재 구현

- FastAPI 가입·로그인, bcrypt 비밀번호 처리, JWT 인증
- 대화방별 최근 5쌍의 문맥과 SQLite 대화 기록
- Gemini의 지역·관광 유형 분석과 답변 생성
- KorPetTourService2 장소 목록·소개정보·반려동물 조건 조회
- 요청 추적 ID와 `logs/app.log` 기록
- SSM SecureString 기반 EC2 설정 전달, Nginx HTTPS, Systemd, SQLite 백업
- Vanilla JS 반응형 화면과 프론트·백엔드 회귀 테스트

## 후속 범위

지역별 관광 자원 수요, Google Maps, 장소 카드와 구조화된 좌표 응답은 아직 구현되지 않았습니다. 실제 API 키를 사용하는 운영 동작·외부 브라우저 시연·현재 EC2 배포 SHA는 별도의 실행 근거로 확인합니다.

## 설정과 배포

Gemini와 KorPetTourService2 요청 타임아웃 기본값은 각각 15초이며, JWT 기본 만료 시간은 60분입니다. EC2 Nginx `proxy_read_timeout` 기본값은 80초입니다. 배포는 Parameter Store SecureString에서 환경을 가져옵니다. DB 검사·예약 백업은 기본 `data/chatbot.db`를 사용하므로 운영 `DATABASE_URL`은 `sqlite:///./data/chatbot.db`로 유지합니다. 자세한 절차와 변수 목록은 [EC2 배포 매뉴얼](ec2_deployment_manual.md)을 따릅니다.

## 검토 시 주의

소스 코드·자동화 테스트·배포 스크립트의 존재만으로 현재 EC2에 같은 코드와 설정이 적용됐다고 단정하지 않습니다. 공개 주소 응답은 AI·DB 저장·관광 API 연결을 검증한 결과와 구분합니다.
