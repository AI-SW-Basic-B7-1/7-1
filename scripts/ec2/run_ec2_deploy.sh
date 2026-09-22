#!/usr/bin/env bash
# B7-1 로컬 배포 실행 스크립트
# AWS Systems Manager로 EC2에 명령을 보내 clone, 환경설정 주입, 서버 배포를 한 번에 수행합니다.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
DEFAULT_REPO_URL="$(git -C "${PROJECT_ROOT}" config --get remote.origin.url 2>/dev/null || true)"

INSTANCE_ID="${INSTANCE_ID:-}"
AWS_REGION_NAME="${AWS_REGION:-ap-northeast-2}"
REPO_URL="${REPO_URL:-${DEFAULT_REPO_URL}}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
APP_USER="${APP_USER:-ubuntu}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/ubuntu/app/B7-1/7-1}"
CLONE_DIR="${CLONE_DIR:-}"
ENV_FILE="${ENV_FILE:-}"
RUN_TESTS=1
WAIT_SECONDS="${WAIT_SECONDS:-900}"

usage() {
    cat <<'EOF'
사용법:
  bash scripts/ec2/run_ec2_deploy.sh --instance-id i-xxxxxxxxxxxxxxxxx [옵션]

필수 옵션:
  --instance-id ID       SSM에 등록된 EC2 인스턴스 ID

주요 옵션:
  --region REGION        AWS 리전 (기본값: ap-northeast-2)
  --repo-url URL         clone할 Git 저장소 URL (기본값: 현재 저장소 origin)
  --branch BRANCH        배포할 Git 브랜치 (기본값: main)
  --project-dir PATH     EC2 애플리케이션 경로 (기본값: /home/ubuntu/app/B7-1/7-1)
  --clone-dir PATH       Git clone 경로 (기본값: project-dir과 동일)
  --env-file PATH        로컬 .env를 SSM으로 전송해 EC2의 project-dir/.env로 저장
  --app-user USER        EC2 애플리케이션 사용자 (기본값: ubuntu)
  --skip-tests            EC2 배포 전 pytest 생략
  --wait-seconds SECONDS  SSM 완료 대기 시간 (기본값: 900)
  -h, --help              도움말 출력

예시:
  bash scripts/ec2/run_ec2_deploy.sh \
    --instance-id i-0123456789abcdef0 \
    --env-file .env

주의:
  이 wrapper는 EC2에서 지정한 브랜치를 clone하므로, 세 스크립트를 포함한 커밋을 먼저 원격 저장소에 push해야 합니다.
  --env-file을 사용하면 .env가 SSM 명령에 포함되어 EC2로 전송됩니다.
  로컬 실행 로그에는 .env 내용과 비밀값을 출력하지 않습니다.
EOF
}

fail() {
    if [[ -n "${LOCAL_LOG:-}" && -f "${LOCAL_LOG}" ]]; then
        printf '[실패] %s\n' "$*" | tee -a "${LOCAL_LOG}" >&2
    else
        printf '[실패] %s\n' "$*" >&2
    fi
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --instance-id)
            [[ $# -ge 2 ]] || fail '--instance-id 값이 필요합니다.'
            INSTANCE_ID="$2"
            shift 2
            ;;
        --region)
            [[ $# -ge 2 ]] || fail '--region 값이 필요합니다.'
            AWS_REGION_NAME="$2"
            shift 2
            ;;
        --repo-url)
            [[ $# -ge 2 ]] || fail '--repo-url 값이 필요합니다.'
            REPO_URL="$2"
            shift 2
            ;;
        --branch)
            [[ $# -ge 2 ]] || fail '--branch 값이 필요합니다.'
            DEPLOY_BRANCH="$2"
            shift 2
            ;;
        --project-dir)
            [[ $# -ge 2 ]] || fail '--project-dir 값이 필요합니다.'
            REMOTE_PROJECT_DIR="$2"
            shift 2
            ;;
        --clone-dir)
            [[ $# -ge 2 ]] || fail '--clone-dir 값이 필요합니다.'
            CLONE_DIR="$2"
            shift 2
            ;;
        --env-file)
            [[ $# -ge 2 ]] || fail '--env-file 값이 필요합니다.'
            ENV_FILE="$2"
            shift 2
            ;;
        --app-user)
            [[ $# -ge 2 ]] || fail '--app-user 값이 필요합니다.'
            APP_USER="$2"
            shift 2
            ;;
        --skip-tests)
            RUN_TESTS=0
            shift
            ;;
        --wait-seconds)
            [[ $# -ge 2 ]] || fail '--wait-seconds 값이 필요합니다.'
            WAIT_SECONDS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "알 수 없는 옵션입니다: $1"
            ;;
    esac
done

[[ -n "${INSTANCE_ID}" ]] || {
    usage >&2
    fail '--instance-id는 필수입니다.'
}
[[ -n "${REPO_URL}" ]] || fail 'Git 저장소 URL을 확인할 수 없습니다. --repo-url을 지정하세요.'
[[ -n "${CLONE_DIR}" ]] || CLONE_DIR="${REMOTE_PROJECT_DIR}"
[[ -f "${SCRIPT_DIR}/deploy_ec2.sh" ]] || fail 'EC2 내부 배포 스크립트를 찾을 수 없습니다.'
[[ -f "${SCRIPT_DIR}/backup_db.sh" ]] || fail 'SQLite 백업 스크립트를 찾을 수 없습니다.'
[[ -z "${ENV_FILE}" || -f "${ENV_FILE}" ]] || fail "로컬 .env 파일을 찾을 수 없습니다: ${ENV_FILE}"
[[ -z "${ENV_FILE}" || -s "${ENV_FILE}" ]] || fail '로컬 .env 파일이 비어 있습니다.'
[[ "${WAIT_SECONDS}" =~ ^[0-9]+$ ]] || fail '--wait-seconds는 숫자여야 합니다.'

LOCAL_LOG_DIR="${LOCAL_LOG_DIR:-${PROJECT_ROOT}/logs}"
mkdir -p "${LOCAL_LOG_DIR}"
LOCAL_LOG="${LOCAL_LOG_DIR}/ec2_deploy_$(date +%Y%m%d_%H%M%S).log"
touch "${LOCAL_LOG}"
chmod 600 "${LOCAL_LOG}"

log_line() {
    printf '%s\n' "$*" | tee -a "${LOCAL_LOG}"
}

log_step() {
    printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*" | tee -a "${LOCAL_LOG}"
}

on_error() {
    local exit_code=$?
    printf '[실패] 로컬 배포 실행이 중단되었습니다. 종료 코드: %s\n' "${exit_code}" | tee -a "${LOCAL_LOG}" >&2
    printf '[실패] 로컬 실행 로그: %s\n' "${LOCAL_LOG}" | tee -a "${LOCAL_LOG}" >&2
    exit "${exit_code}"
}

trap on_error ERR

command -v aws >/dev/null 2>&1 || fail 'AWS CLI가 설치되어 있지 않습니다.'
command -v base64 >/dev/null 2>&1 || fail 'base64 명령을 찾을 수 없습니다.'

quote_for_remote() {
    printf '%q' "$1"
}

log_step '로컬 배포 전제조건 확인'
aws_identity="$(aws sts get-caller-identity --region "${AWS_REGION_NAME}" --query 'Arn' --output text 2>>"${LOCAL_LOG}")"
log_line "AWS 자격증명: ${aws_identity}"
ssm_ping="$(aws ssm describe-instance-information \
    --region "${AWS_REGION_NAME}" \
    --filters "Key=InstanceIds,Values=${INSTANCE_ID}" \
    --query 'InstanceInformationList[0].PingStatus' \
    --output text 2>>"${LOCAL_LOG}")"
[[ "${ssm_ping}" == 'Online' ]] || fail "EC2가 SSM Online 상태가 아닙니다. 현재 상태: ${ssm_ping}"

env_base64=''
if [[ -n "${ENV_FILE}" ]]; then
    log_step '로컬 .env를 안전한 문자로 인코딩'
    env_base64="$(base64 < "${ENV_FILE}" | tr -d '\r\n')"
fi

clone_dir_q="$(quote_for_remote "${CLONE_DIR}")"
project_dir_q="$(quote_for_remote "${REMOTE_PROJECT_DIR}")"
repo_url_q="$(quote_for_remote "${REPO_URL}")"
branch_q="$(quote_for_remote "${DEPLOY_BRANCH}")"
app_user_q="$(quote_for_remote "${APP_USER}")"
deploy_script_q="$(quote_for_remote "${REMOTE_PROJECT_DIR}/scripts/ec2/deploy_ec2.sh")"
clone_parent_q="$(quote_for_remote "$(dirname -- "${CLONE_DIR}")")"

remote_command="$(
    printf 'set -Eeuo pipefail\n'
    printf 'install -d -m 755 -o root -g root %s\n' "${clone_parent_q}"
    printf 'if [[ -d %s/.git ]]; then\n' "${clone_dir_q}"
    printf '  git -c safe.directory=%s -C %s fetch --prune origin %s\n' "${clone_dir_q}" "${clone_dir_q}" "${branch_q}"
    printf '  if git -c safe.directory=%s -C %s show-ref --verify --quiet refs/heads/%s; then\n' "${clone_dir_q}" "${clone_dir_q}" "${branch_q}"
    printf '    git -c safe.directory=%s -C %s checkout %s\n' "${clone_dir_q}" "${clone_dir_q}" "${branch_q}"
    printf '  else\n'
    printf '    git -c safe.directory=%s -C %s checkout -b %s origin/%s\n' "${clone_dir_q}" "${clone_dir_q}" "${branch_q}" "${branch_q}"
    printf '  fi\n'
    printf '  git -c safe.directory=%s -C %s pull --ff-only origin %s\n' "${clone_dir_q}" "${clone_dir_q}" "${branch_q}"
    printf 'else\n'
    printf '  if [[ -e %s && -n "$(find %s -mindepth 1 -maxdepth 1 -print -quit)" ]]; then\n' "${clone_dir_q}" "${clone_dir_q}"
    printf '    echo %q\n' 'clone 경로가 비어 있지 않아 중단합니다.'
    printf '    exit 1\n'
    printf '  fi\n'
    printf '  git clone --branch %s --single-branch %s %s\n' "${branch_q}" "${repo_url_q}" "${clone_dir_q}"
    printf 'fi\n'
    if [[ -n "${env_base64}" ]]; then
        printf 'printf %%s %s | base64 --decode > %s/.env\n' "$(quote_for_remote "${env_base64}")" "${project_dir_q}"
        printf 'chmod 600 %s/.env\n' "${project_dir_q}"
    fi
    printf '[[ -f %s/requirements.txt ]] || { echo %q; exit 1; }\n' "${project_dir_q}" 'requirements.txt가 프로젝트 경로에 없습니다.'
    printf 'APP_USER=%s PROJECT_DIR=%s LOG_DIR=%q RUN_TESTS=%q bash %s\n' \
        "${app_user_q}" "${project_dir_q}" '/var/log/b7-1' "${RUN_TESTS}" "${deploy_script_q}"
)"

# Windows용 AWS CLI shorthand 문법이 원격 Bash의 대괄호를 해석하지 않도록 전체 명령을 인코딩합니다.
remote_command_base64="$(printf '%s' "${remote_command}" | base64 | tr -d '\r\n')"
ssm_command="printf %s ${remote_command_base64} | base64 --decode | bash"

log_step 'SSM으로 EC2 배포 명령 전송'
command_id="$(aws ssm send-command \
    --region "${AWS_REGION_NAME}" \
    --document-name 'AWS-RunShellScript' \
    --instance-ids "${INSTANCE_ID}" \
    --parameters "commands=${ssm_command}" \
    --comment 'B7-1 EC2 SQLite 배포 자동화' \
    --timeout-seconds "${WAIT_SECONDS}" \
    --query 'Command.CommandId' \
    --output text 2>>"${LOCAL_LOG}")"
[[ -n "${command_id}" && "${command_id}" != 'None' ]] || fail 'SSM 명령 ID를 받지 못했습니다.'
log_line "SSM 명령 ID: ${command_id}"

log_step 'EC2 배포 완료 대기'
start_seconds="${SECONDS}"
status='Pending'
while (( SECONDS - start_seconds < WAIT_SECONDS )); do
    status="$(aws ssm get-command-invocation \
        --region "${AWS_REGION_NAME}" \
        --command-id "${command_id}" \
        --instance-id "${INSTANCE_ID}" \
        --query 'Status' \
        --output text 2>>"${LOCAL_LOG}" || true)"
    [[ -n "${status}" && "${status}" != 'None' ]] || status='Pending'
    log_line "[$(date '+%Y-%m-%d %H:%M:%S%z')] SSM 상태: ${status}"
    case "${status}" in
        Success|Failed|TimedOut|Cancelled|Cancelling)
            break
            ;;
    esac
    sleep 3
done

if [[ "${status}" != 'Success' && "${status}" != 'Failed' && "${status}" != 'TimedOut' && "${status}" != 'Cancelled' && "${status}" != 'Cancelling' ]]; then
    fail "SSM 대기 시간이 초과되었습니다. 명령 ID: ${command_id}"
fi

log_step 'EC2 배포 출력 수집'
standard_output="$(aws ssm get-command-invocation \
    --region "${AWS_REGION_NAME}" \
    --command-id "${command_id}" \
    --instance-id "${INSTANCE_ID}" \
    --query 'StandardOutputContent' \
    --output text 2>>"${LOCAL_LOG}")"
standard_error="$(aws ssm get-command-invocation \
    --region "${AWS_REGION_NAME}" \
    --command-id "${command_id}" \
    --instance-id "${INSTANCE_ID}" \
    --query 'StandardErrorContent' \
    --output text 2>>"${LOCAL_LOG}")"

if [[ "${standard_output}" != 'None' && -n "${standard_output}" ]]; then
    printf '%s\n' "${standard_output}" | tee -a "${LOCAL_LOG}"
fi
if [[ "${standard_error}" != 'None' && -n "${standard_error}" ]]; then
    printf '%s\n' "${standard_error}" | tee -a "${LOCAL_LOG}" >&2
fi

[[ "${status}" == 'Success' ]] || fail "EC2 배포에 실패했습니다. SSM 상태: ${status}"

log_step 'EC2 배포 완료'
log_line "로컬 실행 로그: ${LOCAL_LOG}"
log_line 'EC2 배포 로그 경로: /var/log/b7-1/deploy_*.log'
log_line '접속 확인: http://EC2_PUBLIC_IP/'
