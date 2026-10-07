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
SECRET_PARAMETER="${SECRET_PARAMETER:-}"
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
  --secret-parameter NAME
                         EC2가 조회할 Parameter Store SecureString 이름
  --app-user USER        EC2 애플리케이션 사용자 (기본값: ubuntu)
  --skip-tests            EC2 배포 전 pytest 생략
  --wait-seconds SECONDS  SSM 완료 대기 시간 (기본값: 900)
  -h, --help              도움말 출력

예시:
  bash scripts/ec2/run_ec2_deploy.sh \
    --instance-id i-0123456789abcdef0 \
    --secret-parameter /b7-1/production/env

주의:
  이 wrapper는 EC2에서 지정한 브랜치를 clone하므로, 배포 스크립트와 의존 스크립트를 원격 저장소에 먼저 push해야 합니다.
  EC2 인스턴스 역할에 지정 SecureString을 읽을 권한이 필요합니다.
  SSM 명령에는 환경변수 값이 아닌 SecureString의 이름만 전달됩니다.
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
        --secret-parameter)
            [[ $# -ge 2 ]] || fail '--secret-parameter 값이 필요합니다.'
            SECRET_PARAMETER="$2"
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
[[ -n "${SECRET_PARAMETER}" ]] || fail '--secret-parameter는 필수입니다.'
[[ "${SECRET_PARAMETER}" =~ ^/[A-Za-z0-9_./-]+$ ]] || fail 'Parameter Store 이름의 형식이 올바르지 않습니다.'
[[ -n "${REPO_URL}" ]] || fail 'Git 저장소 URL을 확인할 수 없습니다. --repo-url을 지정하세요.'
[[ -n "${CLONE_DIR}" ]] || CLONE_DIR="${REMOTE_PROJECT_DIR}"
[[ -f "${SCRIPT_DIR}/deploy_ec2.sh" ]] || fail 'EC2 내부 배포 스크립트를 찾을 수 없습니다.'
[[ -f "${SCRIPT_DIR}/backup_db.sh" ]] || fail 'SQLite 백업 스크립트를 찾을 수 없습니다.'
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

clone_dir_q="$(quote_for_remote "${CLONE_DIR}")"
project_dir_q="$(quote_for_remote "${REMOTE_PROJECT_DIR}")"
repo_url_q="$(quote_for_remote "${REPO_URL}")"
branch_q="$(quote_for_remote "${DEPLOY_BRANCH}")"
secret_parameter_q="$(quote_for_remote "${SECRET_PARAMETER}")"
region_q="$(quote_for_remote "${AWS_REGION_NAME}")"
app_user_q="$(quote_for_remote "${APP_USER}")"
deploy_script_q="$(quote_for_remote "${REMOTE_PROJECT_DIR}/scripts/ec2/deploy_ec2.sh")"
clone_parent_q="$(quote_for_remote "$(dirname -- "${CLONE_DIR}")")"

remote_command="$(
    printf '%s\n' 'set -Eeuo pipefail'
    printf 'CLONE_DIR=%s PROJECT_DIR=%s APP_USER=%s\n' "${clone_dir_q}" "${project_dir_q}" "${app_user_q}"
    printf '%s\n' 'previous_revision=""' 'previous_branch=""' 'code_updated=0' \
        'env_temp=""' 'env_backup=""' 'awscli_temp=""' 'new_env_installed=0' 'deployment_pid=""' 'service_was_active=0'
    printf '%s\n' 'systemctl is-active --quiet chatbot.service && service_was_active=1 || true'
    printf '%s\n' 'rollback_remote() {' \
        '  local result=$?' \
        '  trap - EXIT' \
        '  set +e' \
        '  rm -f -- "${env_temp:-}"' \
        '  [[ -z "${awscli_temp:-}" ]] || rm -rf -- "$awscli_temp"' \
        '  if [[ "$result" -ne 0 && ( "$code_updated" -eq 1 || "$new_env_installed" -eq 1 ) ]]; then' \
        '    systemctl stop chatbot.service >/dev/null 2>&1' \
        '  fi' \
        '  if [[ "$result" -ne 0 && "$new_env_installed" -eq 1 ]]; then' \
        '    if [[ -n "$env_backup" && -f "$env_backup" ]]; then' \
        '      mv -f -- "$env_backup" "$PROJECT_DIR/.env"' \
        '    else' \
        '      rm -f -- "$PROJECT_DIR/.env"' \
        '    fi' \
        '  else' \
        '    rm -f -- "$env_backup"' \
        '  fi' \
        '  if [[ "$result" -ne 0 && "$code_updated" -eq 1 && -n "$previous_revision" ]]; then' \
        '    if [[ -n "$previous_branch" ]]; then' \
        '      git -c safe.directory="$CLONE_DIR" -C "$CLONE_DIR" checkout "$previous_branch"' \
        '    else' \
        '      git -c safe.directory="$CLONE_DIR" -C "$CLONE_DIR" checkout --detach "$previous_revision"' \
        '    fi' \
        '    git -c safe.directory="$CLONE_DIR" -C "$CLONE_DIR" reset --hard "$previous_revision"' \
        '    chown -R "$APP_USER:$APP_USER" "$PROJECT_DIR"' \
        '    systemctl daemon-reload' \
        '    if [[ "$service_was_active" -eq 1 ]]; then systemctl restart chatbot.service; else systemctl stop chatbot.service; fi' \
        '    printf "%s\\n" "코드와 환경 파일을 이전 배포 상태로 복원했습니다." >&2' \
        '  fi' \
        '  exit "$result"' \
        '}' \
        'handle_remote_signal() {' \
        '  local result="$1"' \
        '  trap - INT TERM' \
        '  if [[ -n "$deployment_pid" ]]; then' \
        '    kill -TERM "$deployment_pid" 2>/dev/null || true' \
        '    wait "$deployment_pid" 2>/dev/null || true' \
        '    deployment_pid=""' \
        '  fi' \
        '  exit "$result"' \
        '}' \
        'trap rollback_remote EXIT' \
        'trap "handle_remote_signal 130" INT' \
        'trap "handle_remote_signal 143" TERM'
    printf 'install -d -m 755 -o root -g root %s\n' "${clone_parent_q}"
    printf 'if [[ -d %s/.git ]]; then\n' "${clone_dir_q}"
    printf '  tracked_changes="$(git -c safe.directory=%s -C %s status --porcelain --untracked-files=no)"\n' "${clone_dir_q}" "${clone_dir_q}"
    printf '  [[ -z "${tracked_changes}" ]] || { echo %q; exit 1; }\n' '원격 저장소에 추적 파일 변경이 있어 배포를 중단합니다.'
    printf '  previous_revision="$(git -c safe.directory=%s -C %s rev-parse HEAD)"\n' "${clone_dir_q}" "${clone_dir_q}"
    printf '  previous_branch="$(git -c safe.directory=%s -C %s rev-parse --abbrev-ref HEAD)"\n' "${clone_dir_q}" "${clone_dir_q}"
    printf '  [[ "${previous_branch}" != HEAD ]] || previous_branch=""\n'
    printf '  git -c safe.directory=%s -C %s fetch --prune origin %s\n' "${clone_dir_q}" "${clone_dir_q}" "${branch_q}"
    printf '  code_updated=1\n'
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
    printf 'install -d -m 755 -o %s -g %s %s\n' "${app_user_q}" "${app_user_q}" "${project_dir_q}"
    printf '%s\n' 'if ! command -v aws >/dev/null 2>&1; then' \
        '  apt-get update' \
        '  apt-get install -y ca-certificates curl unzip' \
        '  case "$(uname -m)" in' \
        '    x86_64) aws_arch=x86_64 ;;' \
        '    aarch64) aws_arch=aarch64 ;;' \
        '    *) echo "지원하지 않는 EC2 아키텍처입니다." >&2; exit 1 ;;' \
        '  esac' \
        '  awscli_temp="$(mktemp -d /tmp/awscli-install.XXXXXX)"' \
        '  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${aws_arch}.zip" -o "${awscli_temp}/awscliv2.zip"' \
        '  unzip -q "${awscli_temp}/awscliv2.zip" -d "${awscli_temp}"' \
        '  "${awscli_temp}/aws/install"' \
        '  rm -rf -- "${awscli_temp}"' \
        '  awscli_temp=""' \
        'fi'
    printf 'env_temp="$(mktemp %s/.env.XXXXXX)"\n' "${project_dir_q}"
    printf 'aws ssm get-parameter --name %s --with-decryption --region %s --query Parameter.Value --output text > "${env_temp}"\n' \
        "${secret_parameter_q}" "${region_q}"
    printf '[[ -s "${env_temp}" ]] || { echo %q; exit 1; }\n' 'SecureString이 비어 있습니다.'
    printf '[[ ! -L %s/.env && ( ! -e %s/.env || -f %s/.env ) ]] || { echo %q; exit 1; }\n' \
        "${project_dir_q}" "${project_dir_q}" "${project_dir_q}" '.env 경로가 일반 파일이 아니어서 중단합니다.'
    printf 'if [[ -f %s/.env ]]; then env_backup="$(mktemp %s/.env.rollback.XXXXXX)"; cp -p -- %s/.env "${env_backup}"; chmod 600 "${env_backup}"; fi\n' \
        "${project_dir_q}" "${project_dir_q}" "${project_dir_q}"
    printf 'chown %s:%s "${env_temp}"\n' "${app_user_q}" "${app_user_q}"
    printf 'chmod 600 "${env_temp}"\n'
    printf 'new_env_installed=1\n'
    printf 'mv -f -- "${env_temp}" %s/.env\n' "${project_dir_q}"
    printf 'env_temp=""\n'
    printf '[[ -f %s/requirements.txt ]] || { echo %q; exit 1; }\n' "${project_dir_q}" 'requirements.txt가 프로젝트 경로에 없습니다.'
    printf 'APP_USER=%s PROJECT_DIR=%s LOG_DIR=%q RUN_TESTS=%q bash %s &\n' \
        "${app_user_q}" "${project_dir_q}" '/var/log/b7-1' "${RUN_TESTS}" "${deploy_script_q}"
    printf 'deployment_pid=$!\nwait "${deployment_pid}"\ndeployment_pid=""\n'
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
        Success|Failed|TimedOut|Cancelled)
            break
            ;;
    esac
    sleep 3
done

if [[ "${status}" != 'Success' && "${status}" != 'Failed' && "${status}" != 'TimedOut' && "${status}" != 'Cancelled' ]]; then
    aws ssm cancel-command \
        --region "${AWS_REGION_NAME}" \
        --command-id "${command_id}" \
        --instance-ids "${INSTANCE_ID}" \
        --output text >>"${LOCAL_LOG}" 2>&1 || true
    cancel_start="${SECONDS}"
    while (( SECONDS - cancel_start < 60 )); do
        status="$(aws ssm get-command-invocation \
            --region "${AWS_REGION_NAME}" \
            --command-id "${command_id}" \
            --instance-id "${INSTANCE_ID}" \
            --query 'Status' \
            --output text 2>>"${LOCAL_LOG}" || true)"
        case "${status}" in
            Success|Failed|TimedOut|Cancelled)
                break
                ;;
        esac
        sleep 3
    done
    case "${status}" in
        Success)
            ;;
        Failed|TimedOut|Cancelled)
            fail "EC2 배포가 취소 또는 실패했습니다. SSM 상태: ${status}, 명령 ID: ${command_id}"
            ;;
        *)
            fail "원격 배포 중단을 확인하지 못했습니다. EC2 상태를 확인하세요. 명령 ID: ${command_id}"
            ;;
    esac
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
log_line '접속 확인: 배포 설정의 SITE_DOMAIN에 HTTPS로 접속합니다.'
