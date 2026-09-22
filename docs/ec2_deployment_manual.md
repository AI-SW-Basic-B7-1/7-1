# B7-1 EC2 배포 스크립트 실행 매뉴얼

## 1. 문서 범위

이 문서는 Windows 개발 환경에서 AWS Systems Manager(SSM)를 사용해 B7-1 애플리케이션을 EC2에 배포하는 절차를 설명합니다.

기본 배포 대상은 다음과 같습니다.

| 항목 | 값 |
| --- | --- |
| AWS 리전 | ap-northeast-2 |
| 배포 브랜치 | develop |
| EC2 인스턴스 ID | i-0b0b18a5347d8a96d |
| EC2 공개 주소 | 15.164.49.77 |
| EC2 사용자 | ubuntu |
| 원격 프로젝트 경로 | /home/ubuntu/app/B7-1/7-1 |

일반적인 배포는 SSH로 원격 명령을 직접 실행하지 않고 SSM을 사용합니다. SSH는 초기 접속, 운영 상태 확인, 비밀키 생성 등의 보조 작업에 사용합니다.

## 2. 세 스크립트의 역할과 실행 시점

배포 흐름은 다음과 같습니다.

~~~text
run_ec2_deploy.sh
        │ 로컬에서 실행
        ▼
AWS SSM Run Command
        │ EC2에서 실행
        ▼
deploy_ec2.sh
        │ 배포 완료 시 Cron 등록
        ▼
backup_db.sh (EC2 시간 기준 매일 04:00)
~~~

| 스크립트 | 실행 위치 | 실행 시점 | 주요 역할 |
| --- | --- | --- | --- |
| scripts/ec2/run_ec2_deploy.sh | 로컬 | 개발자가 배포할 때 수동 실행 | AWS 인증, SSM Online 확인, 원격 브랜치 갱신, .env 전송, SSM 배포 명령 전송 및 결과 대기 |
| scripts/ec2/deploy_ec2.sh | EC2 | run_ec2_deploy.sh가 SSM으로 자동 실행 | 패키지·Swap·Python 가상환경·의존성·Nginx·Systemd 설정, 테스트, 헬스체크, 백업 예약 설정 |
| scripts/ec2/backup_db.sh | EC2 | deploy_ec2.sh가 등록한 Cron에 의해 매일 04:00 실행 | SQLite 온라인 백업, 백업 파일 권한 설정, 7일 초과 백업 삭제 |

backup_db.sh는 배포 중에 즉시 실행되는 것이 아니라 deploy_ec2.sh가 Cron 작업을 등록한 뒤 정해진 시각에 실행됩니다.

## 3. 배포 전 필수 전제조건

### 3.1 로컬 프로그램

- AWS CLI v2
- Git
- Git Bash
- SSH 클라이언트
- 로컬 저장소의 scripts/ec2 세 파일

설치 여부는 다음 명령으로 확인합니다.

~~~bash
aws --version
git --version
bash --version
ssh -V
~~~

### 3.2 AWS 인증과 리전

AWS CLI에 로그인하고 기본 리전을 설정합니다.

~~~bash
aws login --region ap-northeast-2
aws configure set region ap-northeast-2
~~~

인증이 유효한지 확인합니다.

~~~bash
aws sts get-caller-identity --region ap-northeast-2
~~~

임시 인증 세션이 만료되면 배포 전에 aws login을 다시 실행해야 합니다. 운영 환경에서는 root 자격증명보다 필요한 권한만 부여한 IAM 사용자 또는 IAM Identity Center 사용을 권장합니다.

### 3.3 원격 develop 브랜치

run_ec2_deploy.sh는 로컬 파일을 EC2로 복사하는 방식이 아니라 Git 원격 저장소의 지정 브랜치를 EC2에서 clone 또는 pull합니다. 따라서 배포에 필요한 세 스크립트와 애플리케이션 코드가 원격 develop 브랜치에 먼저 존재해야 합니다.

~~~bash
git ls-remote --heads origin develop
git ls-tree -r --name-only origin/develop -- scripts/ec2
~~~

두 번째 명령의 결과에 다음 세 파일이 모두 포함되어야 합니다.

~~~text
scripts/ec2/run_ec2_deploy.sh
scripts/ec2/deploy_ec2.sh
scripts/ec2/backup_db.sh
~~~

현재 확인된 상태에서는 이 세 파일이 원격 develop에 아직 반영되지 않았으므로, 실제 배포 전에 별도로 커밋하고 원격 develop에 반영해야 합니다.

### 3.4 SSM 연결 상태

대상 인스턴스가 SSM에 Online으로 등록되어 있어야 합니다.

~~~bash
aws ssm describe-instance-information --region ap-northeast-2 --filters "Key=InstanceIds,Values=i-0b0b18a5347d8a96d" --query "InstanceInformationList[0].PingStatus" --output text
~~~

정상 결과는 다음과 같습니다.

~~~text
Online
~~~

EC2에는 SSM Agent가 실행 중이어야 하며, 인스턴스 역할에는 Systems Manager 연결에 필요한 권한이 있어야 합니다. 인스턴스가 Online이 아니면 배포를 시작하지 않습니다.

### 3.5 SSH 개인키

SSH 개인키는 로컬에 안전하게 보관하고, 실제 경로는 명령어의 placeholder에 넣습니다.

~~~bash
ssh -i <PRIVATE_KEY_PATH> ubuntu@15.164.49.77
~~~

SSH는 일반 배포의 필수 경로는 아니지만, 서버 상태 확인과 SECRET_KEY 생성에 사용할 수 있습니다.

## 4. 로컬 .env 준비

.env.example을 복사해 로컬 프로젝트 루트에 .env를 만듭니다.

~~~bash
cp .env.example .env
~~~

.env에는 다음 값을 설정해야 합니다.

| 변수 | 설정 기준 |
| --- | --- |
| SECRET_KEY | 예시값이 아닌 충분히 긴 무작위 비밀값 |
| ALGORITHM | 기본값 HS256 |
| ACCESS_TOKEN_EXPIRE_MINUTES | 토큰 만료 시간(분) |
| DATABASE_URL | 기본값 sqlite:///./data/chatbot.db |
| GEMINI_API_KEY | 실제 Gemini API 키 |
| GEMINI_MODEL | 사용할 Gemini 모델명 |
| AI_TIMEOUT_SECONDS | AI 호출 제한 시간(초) |

SECRET_KEY를 SSH로 생성하려면 다음처럼 실행하고 출력된 값을 로컬 .env의 SECRET_KEY에 입력합니다.

~~~bash
ssh -i <PRIVATE_KEY_PATH> ubuntu@15.164.49.77 "openssl rand -hex 32"
~~~

.env는 --env-file .env로 SSM 명령에 포함되어 EC2의 /home/ubuntu/app/B7-1/7-1/.env로 저장됩니다. 원격 배포 스크립트는 SECRET_KEY, GEMINI_API_KEY, DATABASE_URL이 비어 있거나 예시값인지 확인하고, EC2에서 .env 권한을 600으로 설정합니다.

.env는 .gitignore에 포함되어 있으므로 Git에 커밋하지 않습니다.

## 5. 배포 전 점검 순서

다음 순서로 점검합니다.

1. AWS CLI 인증이 유효한지 확인합니다.

   ~~~bash
   aws sts get-caller-identity --region ap-northeast-2
   ~~~

2. 대상 EC2가 SSM Online인지 확인합니다.

   ~~~bash
   aws ssm describe-instance-information --region ap-northeast-2 --filters "Key=InstanceIds,Values=i-0b0b18a5347d8a96d" --query "InstanceInformationList[0].PingStatus" --output text
   ~~~

3. 로컬 .env가 존재하고 비어 있지 않은지 확인합니다.

   ~~~bash
   test -s .env
   ~~~

4. 원격 develop 브랜치에 배포 스크립트 세 개가 존재하는지 확인합니다.

   ~~~bash
   git ls-tree -r --name-only origin/develop -- scripts/ec2
   ~~~

5. 현재 저장소의 origin URL이 배포 대상 저장소인지 확인합니다.

   ~~~bash
   git remote -v
   ~~~

## 6. 배포 실행

모든 전제조건을 확인한 뒤 프로젝트 루트에서 다음 명령을 실행합니다.

~~~bash
bash scripts/ec2/run_ec2_deploy.sh --instance-id i-0b0b18a5347d8a96d --region ap-northeast-2 --branch develop --env-file .env
~~~

run_ec2_deploy.sh는 다음 작업을 순서대로 수행합니다.

1. AWS 자격증명 확인
2. 대상 EC2의 SSM PingStatus 확인
3. 로컬 .env를 전송 가능한 문자열로 변환
4. SSM을 통해 EC2에서 develop 브랜치 clone 또는 pull
5. 원격 프로젝트 경로에 .env 저장
6. EC2에서 deploy_ec2.sh 실행
7. SSM 명령 완료까지 대기
8. 표준 출력과 표준 오류 수집
9. 로컬 및 원격 배포 로그 경로 출력

기본 대기 시간은 900초이며, 테스트를 생략해야 하는 명확한 사유가 있을 때만 다음 옵션을 추가할 수 있습니다.

~~~text
--skip-tests
~~~

기본값인 테스트 실행 상태로 배포하는 것을 권장합니다.

## 7. EC2에서 자동으로 수행되는 작업

deploy_ec2.sh가 SSM에서 root 권한으로 실행되면 다음 작업을 수행합니다.

- 필수 Linux 패키지 설치: nginx, git, python3-venv, sqlite3, cron 등
- 2GB Swap 생성 및 재부팅 후 자동 활성화 등록
- 프로젝트와 SQLite 데이터 디렉터리 권한 설정
- Python 가상환경 생성 및 requirements.txt 설치
- 배포 전 pytest -q 실행
- Nginx를 80번 포트의 reverse proxy로 설정
- SQLite, .env, Git, 로그 파일 외부 접근 차단
- chatbot.service Systemd 서비스 등록 및 재시작
- /api/health 헬스체크
- SQLite 무결성 검사
- SQLite 백업 Cron 등록

백업 Cron은 다음 정책으로 등록됩니다.

| 항목 | 기본값 |
| --- | --- |
| 실행 시각 | EC2 시스템 시간 기준 매일 04:00 |
| 백업 경로 | /home/ubuntu/db_backups |
| 보관 기간 | 7일 |
| 로그 | /home/ubuntu/db_backups/backup.log |

## 8. 배포 후 확인

### 8.1 웹 서비스와 API

브라우저 또는 HTTP 클라이언트에서 다음 주소를 확인합니다.

~~~text
http://15.164.49.77/
http://15.164.49.77/api/health
~~~

DB 파일 직접 접근은 Nginx에서 차단되어 404가 반환되어야 합니다.

~~~text
http://15.164.49.77/data/chatbot.db
~~~

### 8.2 배포 로그

로컬 wrapper 로그는 다음 경로에 생성됩니다.

~~~text
logs/ec2_deploy_YYYYMMDD_HHMMSS.log
~~~

EC2 내부 배포 로그는 다음 경로에 생성됩니다.

~~~text
/var/log/b7-1/deploy_YYYYMMDD_HHMMSS.log
~~~

SSH 접속 후 서비스 상태를 확인할 수 있습니다.

~~~bash
ssh -i <PRIVATE_KEY_PATH> ubuntu@15.164.49.77 "sudo systemctl is-active chatbot.service"
ssh -i <PRIVATE_KEY_PATH> ubuntu@15.164.49.77 "sudo systemctl --no-pager --full status chatbot.service"
~~~

정상 상태는 첫 번째 명령에서 다음과 같이 표시됩니다.

~~~text
active
~~~

### 8.3 백업 예약

백업 예약과 최근 백업 파일을 확인합니다.

~~~bash
ssh -i <PRIVATE_KEY_PATH> ubuntu@15.164.49.77 "sudo cat /etc/cron.d/b7-1-chatbot-backup"
ssh -i <PRIVATE_KEY_PATH> ubuntu@15.164.49.77 "ls -l /home/ubuntu/db_backups"
~~~

## 9. 보안 주의사항

- 실제 API 키, SECRET_KEY, SSH 개인키 내용은 문서·Git·터미널 캡처에 기록하지 않습니다.
- .env는 로컬에서만 관리하고 Git에 커밋하지 않습니다.
- Base64는 암호화가 아니라 전송 형식 변환입니다.
- .env가 로그나 명령어 출력에 노출되었다면 해당 Gemini API 키를 폐기하고 새 키로 교체합니다.
- AWS 임시 인증 세션은 만료되므로 배포 직전에 유효한지 확인합니다.
- 운영 배포에는 root AWS 자격증명보다 최소 권한 IAM 정책을 사용하는 것을 권장합니다.

## 10. 참고 명령어와 공식 문서

~~~bash
# 배포 스크립트 도움말
bash scripts/ec2/run_ec2_deploy.sh --help

# SSM 대상 상태 확인
aws ssm describe-instance-information --region ap-northeast-2
~~~

- [AWS CLI describe-instance-information](https://docs.aws.amazon.com/cli/latest/reference/ssm/describe-instance-information.html)
- [AWS CLI send-command](https://docs.aws.amazon.com/cli/latest/reference/ssm/send-command.html)
- [Linux 인스턴스 SSH 연결](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-to-linux-instance.html)
