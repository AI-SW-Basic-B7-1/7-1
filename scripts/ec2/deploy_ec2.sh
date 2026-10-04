#!/usr/bin/env bash
# B7-1 EC2 내부 배포 스크립트
# AWS Systems Manager Run Command에서 root 권한으로 실행하는 것을 기준으로 합니다.

set -Eeuo pipefail
umask 027

APP_USER="${APP_USER:-ubuntu}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/app/B7-1/7-1}"
LOG_DIR="${LOG_DIR:-/var/log/b7-1}"
SERVICE_NAME="${SERVICE_NAME:-chatbot.service}"
NGINX_SITE_NAME="${NGINX_SITE_NAME:-chatbot}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
RUN_TESTS="${RUN_TESTS:-1}"
BACKUP_DIR="${BACKUP_DIR:-/home/${APP_USER}/db_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
ENV_FILE="${PROJECT_DIR}/.env"
SITE_DOMAIN=""
CERTBOT_WEBROOT="/var/www/letsencrypt"
NGINX_LOG_DIR="/var/log/nginx/b7-1"
NGINX_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
NGINX_SITE_BACKUP=""
NGINX_SITE_EXISTED=0
NGINX_SITE_CHANGED=0
DB_PATH=""
DB_EXISTED_BEFORE=0
PRE_DEPLOY_BACKUP=""
PREVIOUS_REVISION="${PREVIOUS_REVISION:-}"
PREVIOUS_BRANCH="${PREVIOUS_BRANCH:-}"
ENV_BACKUP_PATH="${ENV_BACKUP_PATH:-}"
SERVICE_WAS_ACTIVE=0

fail() {
    printf '[실패] %s\n' "$*" >&2
    if [[ -n "${LOG_FILE:-}" && -f "${LOG_FILE}" ]]; then
        cat "${LOG_FILE}" >&3 2>/dev/null || true
    fi
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail '이 스크립트는 root 권한으로 실행해야 합니다.'
id "${APP_USER}" >/dev/null 2>&1 || fail "애플리케이션 사용자 계정을 찾을 수 없습니다: ${APP_USER}"
[[ -d "${PROJECT_DIR}" ]] || fail "프로젝트 디렉터리를 찾을 수 없습니다: ${PROJECT_DIR}"
[[ -f "${PROJECT_DIR}/requirements.txt" ]] || fail "requirements.txt를 찾을 수 없습니다: ${PROJECT_DIR}"
[[ -f "${ENV_FILE}" ]] || fail '.env 파일이 없습니다. 배포 wrapper가 Parameter Store SecureString을 저장했는지 확인해 주세요.'

APP_HOME="$(getent passwd "${APP_USER}" | cut -d: -f6)"
[[ -n "${APP_HOME}" ]] || fail "사용자의 홈 디렉터리를 확인할 수 없습니다: ${APP_USER}"

mkdir -p "${LOG_DIR}"
chown root:root "${LOG_DIR}"
chmod 700 "${LOG_DIR}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/deploy_$(date +%Y%m%d_%H%M%S).log}"
touch "${LOG_FILE}"
chown root:root "${LOG_FILE}"
chmod 600 "${LOG_FILE}"
exec 3>&1
exec >>"${LOG_FILE}" 2>&1

on_error() {
    local exit_code=$?
    printf '[실패] 줄 번호 %s에서 배포가 중단되었습니다. 종료 코드: %s\n' "${BASH_LINENO[0]:-알 수 없음}" "${exit_code}" >&2
    printf '[실패] 배포 로그: %s\n' "${LOG_FILE}" >&2
    cat "${LOG_FILE}" >&3 2>/dev/null || true
    exit "${exit_code}"
}

trap on_error ERR

if systemctl is-active --quiet "${SERVICE_NAME}"; then
    SERVICE_WAS_ACTIVE=1
fi

on_exit() {
    local result=$?
    trap - EXIT ERR
    if [[ ${result} -ne 0 ]]; then
        set +e
        log_step '배포 실패로 변경 사항 복구'
        if [[ -n "${PREVIOUS_REVISION}" ]]; then
            systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
            if [[ -n "${PRE_DEPLOY_BACKUP}" && -f "${PRE_DEPLOY_BACKUP}" ]]; then
                restore_path="${DB_PATH}.restore.$$"
                install -o "${APP_USER}" -g "${APP_USER}" -m 600 "${PRE_DEPLOY_BACKUP}" "${restore_path}"
                rm -f -- "${DB_PATH}-wal" "${DB_PATH}-shm"
                mv -f -- "${restore_path}" "${DB_PATH}"
            elif [[ "${DB_EXISTED_BEFORE}" -eq 0 && -n "${DB_PATH}" ]]; then
                rm -f -- "${DB_PATH}" "${DB_PATH}-wal" "${DB_PATH}-shm"
            fi
        fi
        if [[ -n "${ENV_BACKUP_PATH}" && -f "${ENV_BACKUP_PATH}" ]]; then
            install -o "${APP_USER}" -g "${APP_USER}" -m 600 "${ENV_BACKUP_PATH}" "${ENV_FILE}"
        fi
        if [[ "${NGINX_SITE_CHANGED}" -eq 1 && "${NGINX_SITE_EXISTED}" -eq 1 && -n "${NGINX_SITE_BACKUP}" && -f "${NGINX_SITE_BACKUP}" ]]; then
            install -o root -g root -m 644 "${NGINX_SITE_BACKUP}" "${NGINX_AVAILABLE}"
            ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
            nginx -t && systemctl reload nginx
        elif [[ "${NGINX_SITE_CHANGED}" -eq 1 && -n "${NGINX_SITE_BACKUP}" ]]; then
            rm -f -- "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
            nginx -t && systemctl reload nginx
        fi
        if [[ -n "${PREVIOUS_REVISION}" ]]; then
            if [[ -n "${PREVIOUS_BRANCH}" ]]; then
                git -c safe.directory="${PROJECT_DIR}" -C "${PROJECT_DIR}" checkout --force "${PREVIOUS_BRANCH}"
            fi
            git -c safe.directory="${PROJECT_DIR}" -C "${PROJECT_DIR}" reset --hard "${PREVIOUS_REVISION}"
            chown -R "${APP_USER}:${APP_USER}" "${PROJECT_DIR}"
        fi
        if [[ "${SERVICE_WAS_ACTIVE}" -eq 1 ]]; then
            systemctl restart "${SERVICE_NAME}"
            systemctl is-active --quiet "${SERVICE_NAME}"
        fi
        if [[ -n "${PREVIOUS_REVISION}" ]]; then
            printf '복구 기준 커밋: %s\n' "${PREVIOUS_REVISION}"
        fi
        if [[ -n "${PRE_DEPLOY_BACKUP}" ]]; then
            printf '배포 전 DB 백업: %s\n' "${PRE_DEPLOY_BACKUP}"
        fi
    elif [[ ${result} -eq 0 && -n "${ENV_BACKUP_PATH}" ]]; then
        rm -f -- "${ENV_BACKUP_PATH}"
    fi
    if [[ ${result} -eq 0 && -n "${NGINX_SITE_BACKUP}" ]]; then
        rm -f -- "${NGINX_SITE_BACKUP}"
    fi
    exit "${result}"
}
trap on_exit EXIT

log_step() {
    printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

run_cmd() {
    local description="$1"
    shift
    log_step "${description}"
    printf '명령:'
    printf ' %q' "$@"
    printf '\n'
    "$@"
}

run_as_app_in_project() {
    runuser -u "${APP_USER}" -- env HOME="${APP_HOME}" bash -c 'cd "$1"; shift; exec "$@"' bash "${PROJECT_DIR}" "$@"
}

env_value() {
    local key="$1"
    local source="${2:-${ENV_FILE}}"
    local raw

    raw="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "${source}" | head -n 1 || true)"
    raw="${raw#*=}"
    raw="${raw#"${raw%%[![:space:]]*}"}"
    raw="${raw%"${raw##*[![:space:]]}"}"
    raw="${raw#\"}"
    raw="${raw%\"}"
    printf '%s' "${raw}"
}

log_step '운영 환경변수 필수 항목 확인'
secret_key="$(env_value SECRET_KEY)"
gemini_api_key="$(env_value GEMINI_API_KEY)"
database_url="$(env_value DATABASE_URL)"
SITE_DOMAIN="$(env_value SITE_DOMAIN)"
if [[ -n "${ENV_BACKUP_PATH}" && -f "${ENV_BACKUP_PATH}" ]]; then
    previous_database_url="$(env_value DATABASE_URL "${ENV_BACKUP_PATH}")"
    [[ "${previous_database_url}" == "${database_url}" ]] || fail 'DATABASE_URL 변경은 DB 이전 계획을 별도로 준비해야 합니다.'
fi
[[ -n "${secret_key}" ]] || fail 'SECRET_KEY가 비어 있습니다.'
[[ -n "${gemini_api_key}" ]] || fail 'GEMINI_API_KEY가 비어 있습니다.'
[[ -n "${database_url}" ]] || fail 'DATABASE_URL이 비어 있습니다.'
[[ -n "${SITE_DOMAIN}" ]] || fail 'SITE_DOMAIN이 비어 있습니다.'
[[ "${secret_key}" != *'your_super_secret_jwt_key_here'* ]] || fail 'SECRET_KEY에 예시값이 남아 있습니다.'
[[ "${gemini_api_key}" != *'여기에_본인의_Gemini_API_Key'* ]] || fail 'GEMINI_API_KEY에 예시값이 남아 있습니다.'
[[ "${SITE_DOMAIN}" =~ ^[A-Za-z0-9.-]+$ && "${SITE_DOMAIN}" != *..* && "${SITE_DOMAIN}" != .* && "${SITE_DOMAIN}" != -* && "${SITE_DOMAIN}" != *- ]] || fail 'SITE_DOMAIN 형식이 올바르지 않습니다.'
[[ "${database_url}" == sqlite:///* ]] || fail 'SQLite 파일 URL 형식의 DATABASE_URL이 필요합니다.'
database_path="${database_url#sqlite:///}"
if [[ "${database_path}" == /* ]]; then
    database_candidate="${database_path}"
else
    database_candidate="${PROJECT_DIR}/${database_path}"
fi
DB_PATH="$(realpath -m -- "${database_candidate}")"
unset secret_key gemini_api_key database_url previous_database_url

BACKUP_SCRIPT="${PROJECT_DIR}/scripts/ec2/backup_db.sh"
[[ -f "${BACKUP_SCRIPT}" ]] || fail "DB 백업 스크립트를 찾을 수 없습니다: ${BACKUP_SCRIPT}"
if [[ "${SERVICE_WAS_ACTIVE}" -eq 1 ]]; then
    run_cmd '일관된 DB 백업과 배포 중 쓰기 방지를 위해 챗봇 서비스 중지' systemctl stop "${SERVICE_NAME}"
fi
if [[ -f "${DB_PATH}" ]]; then
    DB_EXISTED_BEFORE=1
    BACKUP_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
    PRE_DEPLOY_BACKUP="${BACKUP_DIR}/predeploy_${BACKUP_TIMESTAMP}.db"
    run_cmd '배포 전 운영 DB 백업 디렉터리 준비' install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "${BACKUP_DIR}"
    run_cmd '배포 전 DB 백업 생성' runuser -u "${APP_USER}" -- env \
        HOME="${APP_HOME}" DB_PATH="${DB_PATH}" BACKUP_DIR="${BACKUP_DIR}" \
        BACKUP_PREFIX=predeploy BACKUP_TIMESTAMP="${BACKUP_TIMESTAMP}" REQUIRE_DB=1 \
        bash "${BACKUP_SCRIPT}"
else
    printf '기존 운영 DB가 없어 배포 전 백업은 생략합니다: %s\n' "${DB_PATH}"
fi

run_cmd 'EC2 시간대 설정' timedatectl set-timezone Asia/Seoul
configured_timezone="$(timedatectl show --property=Timezone --value)"
[[ "${configured_timezone}" == 'Asia/Seoul' ]] || fail "EC2 시간대 확인에 실패했습니다: ${configured_timezone}"

export DEBIAN_FRONTEND=noninteractive
run_cmd '패키지 목록 갱신' apt-get update
run_cmd '기본 패키지 업그레이드' apt-get upgrade -y
run_cmd '배포 필수 패키지 설치' apt-get install -y awscli ca-certificates certbot curl cron git logrotate nginx python3 python3-pip python3-venv sqlite3

log_step '2GB Swap 구성'
if swapon --show=NAME --noheadings | awk '{print $1}' | grep -Fxq "${SWAP_FILE}"; then
    printf '이미 활성화된 Swap 파일을 확인했습니다: %s\n' "${SWAP_FILE}"
elif [[ -e "${SWAP_FILE}" ]]; then
    fail "이미 존재하지만 Swap으로 활성화되지 않은 파일이 있습니다: ${SWAP_FILE}"
else
    run_cmd 'Swap 파일 생성' fallocate -l "${SWAP_SIZE}" "${SWAP_FILE}"
    run_cmd 'Swap 파일 권한 제한' chmod 600 "${SWAP_FILE}"
    run_cmd 'Swap 영역 초기화' mkswap "${SWAP_FILE}"
    run_cmd 'Swap 활성화' swapon "${SWAP_FILE}"
fi

if ! grep -Fqx "${SWAP_FILE} none swap sw 0 0" /etc/fstab; then
    log_step '재부팅 후 Swap 자동 활성화 등록'
    printf '%s none swap sw 0 0\n' "${SWAP_FILE}" >> /etc/fstab
fi
run_cmd '메모리 및 Swap 상태 기록' free -h

run_cmd '프로젝트 소유권 정리' chown -R "${APP_USER}:${APP_USER}" "${PROJECT_DIR}"
run_cmd 'SQLite 디렉터리 권한 설정' install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "$(dirname -- "${DB_PATH}")"
run_cmd '애플리케이션 로그 디렉터리 생성' install -d -o "${APP_USER}" -g "${APP_USER}" -m 750 "${PROJECT_DIR}/logs"
run_cmd '운영 환경변수 파일 권한 설정' chmod 600 "${ENV_FILE}"

if [[ -f "${DB_PATH}" ]]; then
    run_cmd '기존 SQLite 파일 권한 설정' chmod 600 "${DB_PATH}"
else
    printf '아직 생성되지 않은 SQLite 파일입니다. 애플리케이션 시작 시 생성됩니다: %s\n' "${DB_PATH}"
fi

run_cmd 'Python 가상환경 생성' run_as_app_in_project python3 -m venv venv
run_cmd 'pip 업데이트' run_as_app_in_project "${PROJECT_DIR}/venv/bin/python" -m pip install --upgrade pip
run_cmd 'Python 의존성 설치' run_as_app_in_project "${PROJECT_DIR}/venv/bin/python" -m pip install -r requirements.txt

if [[ "${RUN_TESTS}" == '1' ]]; then
    run_cmd '배포 전 pytest 실행' run_as_app_in_project "${PROJECT_DIR}/venv/bin/python" -m pytest -q
else
    log_step '배포 전 pytest 생략'
fi

NGINX_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
mkdir -p /var/backups/b7-1-nginx
NGINX_SITE_BACKUP="$(mktemp /var/backups/b7-1-nginx/deploy.XXXXXXXX)"
if [[ -f "${NGINX_AVAILABLE}" ]]; then
    cp -p -- "${NGINX_AVAILABLE}" "${NGINX_SITE_BACKUP}"
    NGINX_SITE_EXISTED=1
fi

CERTIFICATE_PATH="/etc/letsencrypt/live/${SITE_DOMAIN}/fullchain.pem"
CERTIFICATE_KEY_PATH="/etc/letsencrypt/live/${SITE_DOMAIN}/privkey.pem"
run_cmd 'ACME 인증 경로 생성' install -d -o root -g root -m 755 "${CERTBOT_WEBROOT}"
NGINX_SITE_CHANGED=1
if [[ ! -s "${CERTIFICATE_PATH}" || ! -s "${CERTIFICATE_KEY_PATH}" ]]; then
    challenge_temp_file="$(mktemp)"
    cat > "${challenge_temp_file}" <<EOF
server {
    listen 80;
    server_name ${SITE_DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${CERTBOT_WEBROOT};
    }

    location / {
        return 404;
    }
}
EOF
    run_cmd '인증서 발급용 HTTP 사이트 적용' install -o root -g root -m 644 "${challenge_temp_file}" "${NGINX_AVAILABLE}"
    rm -f -- "${challenge_temp_file}"
    run_cmd '인증서 발급용 사이트 활성화' ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
    run_cmd '인증서 발급용 Nginx 문법 검사' nginx -t
    run_cmd 'Nginx 시작' systemctl enable --now nginx
    run_cmd '인증서 발급용 Nginx 적용' systemctl reload nginx
    run_cmd 'Let’s Encrypt 인증서 최초 발급' certbot certonly --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring --webroot -w "${CERTBOT_WEBROOT}" -d "${SITE_DOMAIN}"
fi

nginx_temp_file="$(mktemp)"
cat > "${nginx_temp_file}" <<EOF
server {
    listen 80;
    listen 443 ssl;
    server_name ${SITE_DOMAIN};

    ssl_certificate ${CERTIFICATE_PATH};
    ssl_certificate_key ${CERTIFICATE_KEY_PATH};
    ssl_protocols TLSv1.2 TLSv1.3;
    if (\$scheme = http) {
        rewrite ^(?!/\.well-known/acme-challenge/).* https://${SITE_DOMAIN}\$request_uri permanent;
    }

    client_max_body_size 2M;

    location ^~ /.well-known/acme-challenge/ {
        root ${CERTBOT_WEBROOT};
    }

    # SQLite 데이터베이스와 환경설정 파일의 외부 다운로드를 차단합니다.
    location ~* \\.(db|sqlite|sqlite3|env|git|log)$ {
        deny all;
        return 404;
    }

    # data 디렉터리 직접 접근을 차단합니다.
    location ^~ /data/ {
        deny all;
        return 404;
    }

    location /static/ {
        # FastAPI가 정적 파일을 제공하므로 Nginx의 홈 디렉터리 권한에 의존하지 않습니다.
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        expires 1d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 30s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }
}
EOF
run_cmd 'Nginx 사이트 설정 설치' install -o root -g root -m 644 "${nginx_temp_file}" "${NGINX_AVAILABLE}"
rm -f "${nginx_temp_file}"
run_cmd '기본 Nginx 사이트 비활성화' rm -f /etc/nginx/sites-enabled/default
run_cmd '챗봇 Nginx 사이트 활성화' ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
run_cmd 'Nginx 문법 검사' nginx -t
run_cmd 'Nginx 부팅 자동 시작 설정' systemctl enable nginx
run_cmd 'Nginx 재시작' systemctl restart nginx
run_cmd 'Let’s Encrypt 인증서 갱신 점검' certbot certonly --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring --webroot -w "${CERTBOT_WEBROOT}" -d "${SITE_DOMAIN}"
install -d -o root -g root -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx <<'HOOK'
#!/bin/sh
systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
run_cmd '인증서 자동 갱신 타이머 활성화' systemctl enable --now certbot.timer

SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}"
systemd_temp_file="$(mktemp)"
cat > "${systemd_temp_file}" <<EOF
[Unit]
Description=B7-1 AI 챗봇 FastAPI 서비스
After=network.target

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${PROJECT_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=${ENV_FILE}
ExecStart=${PROJECT_DIR}/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
run_cmd 'Systemd 서비스 파일 설치' install -o root -g root -m 644 "${systemd_temp_file}" "${SYSTEMD_UNIT}"
rm -f "${systemd_temp_file}"
run_cmd 'Systemd 설정 다시 읽기' systemctl daemon-reload
run_cmd '챗봇 서비스 부팅 자동 시작 설정' systemctl enable "${SERVICE_NAME}"
run_cmd '챗봇 서비스 재시작' systemctl restart "${SERVICE_NAME}"

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    journalctl -u "${SERVICE_NAME}" --no-pager -n 50
    fail "챗봇 서비스가 실행 중이 아닙니다: ${SERVICE_NAME}"
fi

run_cmd 'Nginx 요청 추적 및 로그 회전 설정 재적용' env \
    "PROJECT_DIR=${PROJECT_DIR}" "SITE_CONFIG=${NGINX_ENABLED}" \
    "VERIFY_BASE_URL=https://${SITE_DOMAIN}" \
    "VERIFY_RESOLVE=${SITE_DOMAIN}:443:127.0.0.1" \
    "NGINX_LOG_DIR=${NGINX_LOG_DIR}" \
    bash "${PROJECT_DIR}/scripts/ec2/configure_nginx_logs.sh"

run_cmd 'DB 백업 디렉터리 생성' install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "${BACKUP_DIR}"
BACKUP_SCRIPT="${PROJECT_DIR}/scripts/ec2/backup_db.sh"
[[ -f "${BACKUP_SCRIPT}" ]] || fail "DB 백업 스크립트를 찾을 수 없습니다: ${BACKUP_SCRIPT}"
run_cmd 'DB 백업 스크립트 실행 권한 설정' chmod 750 "${BACKUP_SCRIPT}"
touch "${BACKUP_DIR}/backup.log"
chown "${APP_USER}:${APP_USER}" "${BACKUP_DIR}/backup.log"
chmod 600 "${BACKUP_DIR}/backup.log"
cron_quote() {
    local value
    printf -v value '%q' "$1"
    value="${value//%/\\%}"
    printf '%s' "$value"
}

CRON_FILE='/etc/cron.d/b7-1-chatbot-backup'
cron_temp_file="$(mktemp)"
cron_db_path="$(cron_quote "${DB_PATH}")"
cron_backup_dir="$(cron_quote "${BACKUP_DIR}")"
cron_backup_script="$(cron_quote "${BACKUP_SCRIPT}")"
cron_backup_log="$(cron_quote "${BACKUP_DIR}/backup.log")"
printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n0 4 * * * %s DB_PATH=%s BACKUP_DIR=%s RETENTION_DAYS=%s REQUIRE_DB=1 %s >> %s 2>&1\n' \
    "${APP_USER}" "${cron_db_path}" "${cron_backup_dir}" "${RETENTION_DAYS}" "${cron_backup_script}" "${cron_backup_log}" > "${cron_temp_file}"
run_cmd 'SQLite 일일 백업 예약 설치' install -o root -g root -m 644 "${cron_temp_file}" "${CRON_FILE}"
rm -f "${cron_temp_file}"
run_cmd 'Cron 부팅 자동 시작 설정' systemctl enable cron
run_cmd 'Cron 재시작' systemctl restart cron

log_step '서비스 헬스체크 대기'
health_ok=0
for attempt in $(seq 1 30); do
    if curl --resolve "${SITE_DOMAIN}:443:127.0.0.1" -fsS --max-time 3 "https://${SITE_DOMAIN}/api/health"; then
        printf '\n'
        health_ok=1
        break
    fi
    sleep 1
done
[[ "${health_ok}" -eq 1 ]] || {
    journalctl -u "${SERVICE_NAME}" --no-pager -n 50
    fail 'HTTPS 헬스체크에 실패했습니다.'
}

http_redirect="$(curl --resolve "${SITE_DOMAIN}:80:127.0.0.1" -sS --max-time 5 -o /dev/null -w '%{http_code} %{redirect_url}' "http://${SITE_DOMAIN}/api/health" || true)"
[[ "${http_redirect}" == "301 https://${SITE_DOMAIN}/api/health" ]] || fail "HTTP에서 HTTPS 전환을 확인하지 못했습니다: ${http_redirect}"

for static_path in /static/css/style.css /static/js/auth.js /static/js/app.js; do
    if ! curl --resolve "${SITE_DOMAIN}:443:127.0.0.1" -fsS --max-time 5 "https://${SITE_DOMAIN}${static_path}" -o /dev/null; then
        fail "Nginx 정적 파일 점검에 실패했습니다: ${static_path}"
    fi
done

db_block_status="$(curl --resolve "${SITE_DOMAIN}:443:127.0.0.1" -sS --max-time 5 -o /dev/null -w '%{http_code}' "https://${SITE_DOMAIN}/data/chatbot.db" || true)"
[[ "${db_block_status}" == '404' ]] || fail "Nginx의 DB 파일 차단 검증에 실패했습니다. HTTPS 상태: ${db_block_status}"

[[ -f "${DB_PATH}" ]] || fail "헬스체크 이후에도 SQLite 파일이 생성되지 않았습니다: ${DB_PATH}"
database_integrity="$(sqlite3 "${DB_PATH}" 'PRAGMA integrity_check;')"
[[ "${database_integrity}" == 'ok' ]] || fail "SQLite 무결성 확인에 실패했습니다: ${database_integrity}"
printf '%s\n' 'SQLite 무결성 확인: ok'
run_cmd '챗봇 서비스 상태 기록' systemctl --no-pager --full status "${SERVICE_NAME}"

log_step 'EC2 배포 완료'
printf '배포 로그: %s\n' "${LOG_FILE}"
printf '애플리케이션 경로: %s\n' "${PROJECT_DIR}"
printf 'Systemd 서비스: %s\n' "${SERVICE_NAME}"
printf 'Nginx 보안 검증: HTTPS, HTTP 전환, DB 직접 접근 404 확인\n'
printf 'SQLite 백업 예약: 매일 04:00, 보관 기간 %s일\n' "${RETENTION_DAYS}"
cat "${LOG_FILE}" >&3
